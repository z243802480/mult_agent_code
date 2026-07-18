# ADR-0031：长期记忆分层补活水——模型主动写通道 + 索引召回 + goal 归档

- 状态：Accepted（2026-07-18）
- 关联：[ADR-0016 认知归模型/边界归状态]、[ADR-0024 doer 读回持久记忆]、
  `tools/memory_tools.py`、`core/context_loader.py`、`core/active_goal_memory.py`、
  brief `benchmarks/reference_briefs/S89-long-term-memory-model-channel.md`
- 触发：用户「长期记忆这块如何设计和完善」→ 现状调查证实骨架（读回）健康、
  活水（写入/召回/固化）缺失 → 用户「参考主流实现把这块给改好吧。按你建议进行」。

## 1. 背景（Context）

ADR-0024 闭合后 doer 能读回记忆，但整个记忆系统仍是**harness 独白**：

- 所有 memory_entry 写入都是 harness 固定事件点的确定性抽取（决策解决/acceptance
  失败/provider 失败）。**模型不能主动记住任何东西**——而"这个方案试过、因为 X 失败"
  这类最有价值的教训只有模型在跑的当下知道。schema 的 7 个类型 5 个没有写通道。
- 召回=时间序最后 8 条全文。条目积累后，久远但正好相关的教训结构上永远轮不到。
- `active_goal` 单槽（`memory_id="active-goal"`），换 goal 即覆写，历史死在原地。
- append-only 无去重：跨 run 重复学同一课，每条都占索引位。

## 2. 决策（Decision）

三层记忆各补其缺，机制对标主流（Claude Code 索引+按需读取 / MemGPT 分层检索 /
Reflexion 结项蒸馏），不抄实现：

1. **`remember` 工具**：模型判断"什么值得记住"（认知归模型），harness 只做边界
   （schema 校验、2000 字符/条、20 条/run、写时按内容去重幂等、
   `source={kind:"model", run_id}` 溯源、独立文件 `model_notes.jsonl`）。
   harness 既有确定性写点**保留不动**——两通道互补：harness 记客观事实，模型记判断。
2. **索引召回**：`ContextLoader._memory` 改产**一行式索引**（默认最新 40 条、
   summary 200 字符、truncated 标记、source_file 溯源、跨文件内容去重）；
   `recall_memory(memory_id)` 按需取全文（id 跨文件可撞 → 返回全部匹配+文件名）。
   相关性判断交给模型（它看着索引挑），**不上向量 RAG**——量级不配、文件系统优先。
3. **goal 归档**：`write_from_run` 见 goal_id 变更先把旧记录押进 `memory/goals/`
   （上限 20、按 mtime 修剪）；蒸馏的模型半边走 remember 的工具描述与 methodology
   guidance 引导（不做 harness 强制步骤）。

## 3. ADR-0016 合规

- **认知归模型**：记什么、何时记、召回哪条，全部模型涌现；工具描述只给 when-to-use
  建议。harness 不判断"这条值不值得记"。
- **边界归状态**：schema 校验、长度/条数预算、去重、归档上限、溯源字段——全是
  确定性持久化边界。
- **证据型**：索引行带 provenance；`remember` 的写预算耗尽/类型非法都是显式失败
  （教模型合法词表），不静默吞。

## 4. 一致性检查（Conformance）

- [x] 接线完整（五处）：defaults 注册、`_TOOL_KINDS`（unknown→deny，漏加=能力闸拒）、
  planner `_allowed_tools`（全任务类含 readonly——research/diagnostic 的教训最值得记）、
  agent_tool_surface（模型可见+引导）、budget STATE_TOOLS/READ_ONLY_TOOLS。
- [x] `runtime_context["memory"]` 保持 list 形状（planner `_context_note` 的
  `len()` 消费者不破）；字段 content→summary+truncated 属有意变更，测试同步。
- [x] 真栈闭环测试：run1 模型经真实 execute 链调 remember 落盘 → run2 prompt 实证
  含该记忆 → recall_memory 取回全文（`test_context_injection.py`）。
- [x] 单测 13 条新增；全量 pytest / ruff / mypy_ratchet 绿。

## 5. 明确不做（等证据）

跨 workspace 全局层（`~/.asteria`）、Studio 记忆管理 UI（G14 只读边界不变）、
向量检索、周期性模型 consolidation pass——各自的触发证据见 brief §明确不做。

## 6. 回退（Rollback）

- 工具：defaults 里去掉两行注册 + surface/`_TOOL_KINDS`/planner/budget 各删两个名字。
- 索引：`_memory` 恢复旧投影即回到"最后 8 条全文"。
- 归档：删 `_archive_previous_goal` 调用。
  三者独立可回退；`model_notes.jsonl` 与 `memory/goals/` 是纯增量文件，删除即净。
