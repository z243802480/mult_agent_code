# S89 — 长期记忆补活水：模型主动写通道 + 索引召回 + goal 归档

## 用户拍的板（2026-07-18）

「参考主流实现把这块给改好吧。按你建议进行」——授权按本会话给出的四刀方案落地
（刀五跨 workspace 全局层显式排除：攒证据再做）。

## 出发点（先核实的现状，非猜测）

调查结论（Explore 全链路 + 逐点读码核实）：读回链路健康（ADR-0024 三刀已闭合、
compaction 落盘可回读、artifact 磁盘对账），真差距在写入与召回：

1. **模型没有"记住"的写通道**——所有 memory_entry 写入都是 harness 固定事件点
   （resume 决策 / acceptance 失败 / provider 失败），7 个 schema 类型 5 个饿死；
   "什么值得记住"是认知判断，按 ADR-0016 应归模型。
2. **召回是时间尾巴**——`ContextLoader._memory` 只喂时间序最后 8 条全文，
   三周前正好相关的 failure_lesson 结构上永远轮不到。
3. **goal 结项即覆写**——`memory_id="active-goal"` 单槽，换 goal 历史死在覆写里。
4. **只写不修剪**——append-only 无去重，重复学同一课每条都进文件。

## 主流对标（机制学习，不抄实现）

- **Claude Code 记忆**：每条记忆一个条目 + 一行式索引（MEMORY.md）常驻上下文 +
  全文按需读取 + 写前查重；写入由模型判断。→ 本刀的 index + recall_memory + 写时去重。
- **MemGPT/Letta 分层**：working / archival 分层 + 按需检索页入。→ 本仓已有
  active_goal（working）/ memory_entry（archival）两层，缺的是检索页入一侧。
- **Reflexion / generative agents**：episode 结束做 reflection 蒸馏。→ goal 归档
  （确定性半边）+ remember 工具引导「结项前沉淀教训」（模型半边）。

## 四刀落点

1. **remember 工具**（`tools/memory_tools.py`）：模型主动写 memory_entry 到
   `.asteria/memory/model_notes.jsonl`。边界归 harness：schema 校验、2000 字符/条、
   20 条/run、写时按内容去重（幂等）、source={kind:model, run_id} 溯源。
   接线五处缺一不可：defaults 注册、`_TOOL_KINDS`（unknown→deny，不加=能力闸拒）、
   planner `_allowed_tools`（含 readonly 集：research/diagnostic 的教训正是最值得记的）、
   agent_tool_surface 模型面（含 when-to-use 引导）、budget STATE_TOOLS。
2. **索引 + recall_memory**：`_memory()` 从「最后 8 条全文」改为「最新 40 条一行式
   索引」（每条 summary 200 字符 + truncated 标记 + source_file），相关性判断交给
   模型，截断的用 recall_memory(memory_id) 取全文（id 跨文件可撞，返回全部匹配 +
   文件溯源）。**不上向量 RAG**：条目量级不配，文件系统优先约束仍在，量级上来再
   证据驱动升级（SQLite FTS 是下一站，不是嵌入）。
3. **goal 归档**：`write_from_run` 检测 goal_id 变更 → 旧记录押进
   `memory/goals/`（上限 20，按 mtime 修剪——文件名秒级时间戳同秒会撞）。蒸馏由
   remember 的工具描述 + methodology guidance 引导（模型认知，不做 harness 强制）。
4. **读时卫生**：坏行跳过（沿用）+ 跨文件内容去重（新旧同文保最新）+ 硬上限。

## 护栏（设计即立）

- **记忆是数据不是指令**：索引行带 provenance（source_file/created_at/confidence），
  以背景事实形态进 prompt。
- **注入永远有界**：40×200 字符 ≈ 8KB 封顶，与 workspace_files（24KB）同量级。
- **模型写通道的毒化解毒剂**：独立文件（model_notes.jsonl 一删即净）+ 溯源 +
  写预算 + confidence 字段。Studio 展示/编辑属刀五，等证据。

## 验收

1. 单测：memory_tools 8 条（schema/溯源/幂等/预算/跨文件撞 id/坏行）+
   context_loader 索引 3 条（去重/截断/上限）+ active_goal 归档 2 条。
2. **真栈闭环**（`test_context_injection.py`）：run1 模型经真实 execute spine 调
   remember（planner 契约→能力闸→gateway→落盘）→ run2 的 prompt 里实证出现该记忆
   （saw_memory_index）→ recall_memory ok=True 取回全文。
3. 回归：全量 pytest + ruff + mypy_ratchet exit 0。

## 明确不做（本刀）

- 跨 workspace 全局记忆（`~/.asteria` 用户偏好库）——内部发动机定位下优先级低，等证据。
- Studio 记忆管理 UI / memory_entry 展示——G14 只读边界不变，刀五另案。
- 向量检索/嵌入——见上。
- 周期性模型 consolidation pass——读时卫生已覆盖住最咬人的重复问题；模型 pass 需要
  新的触发时机设计（何时跑、谁付费），等真实腐烂证据再立刀。
