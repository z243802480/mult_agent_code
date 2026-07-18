# ADR-0032：上下文管理补活水——压缩真缩、真尺子、循环历史微压缩

- 状态：Accepted（2026-07-18）
- 关联：[ADR-0016 认知归模型/边界归状态]、[ADR-0031 长期记忆分层]、
  `core/model_driven_turn.py`、`core/context_budget.py`、`core/budget.py`、
  `models/metered.py`、`commands/execute_command.py`、`commands/run_command.py`、
  brief `benchmarks/reference_briefs/S90-context-management-live-compaction.md`
- 触发：用户「对话管理跟记忆管理一样重要，包括中间的压缩对话功能」→ 调查证实
  重审计 20260718 §3 第 3 条债（「压缩」只写快照从不缩活提示）→ 用户「按你建议进行完善修复」。

## 1. 背景（Context）

执行循环的对话结构本身健康（每 task 从零播种、≤12 轮保险丝、grounding 每 task 重建），
但压力处置全是「量 + 记 + 快照 + 到阈值停下等人」：

- `_compact_boundary` 算出 preserve/droppable **无人应用**到发给模型的上下文；
- 0.9 hard_stop 直接 pause 整个 run 等人审——与 set-and-forget 产能观冲突
  （人只该在计划/高危处被打断，不该在半夜被一个可自动回收的上下文压力叫醒）；
- 循环内 observation payload 单条有 6KB 上限但**累积无界**；
- token 计量=字符启发式，窗口全局硬编码 200k 不随 provider 变——真窗口更小的模型
  （本仓目标栈 glm/minimax）的阈值量在虚构天花板上。

## 2. 决策（Decision）

三刀，全部是**确定性边界**（不引入模型驱动摘要——grounding 本就是确定性重建的，
段级丢弃 + S89 的记忆索引/ActiveGoalMemory 兜底语义即可；摘要环节会引入虚构风险，等证据）：

1. **循环历史微压缩**（`run_model_driven_turn`）：`history_char_budget`（默认 60k 字符）
   超限时把**最旧** observation 消息的 payload 坍缩为摘要+「如何再生」提示；最近
   `keep_recent_observation_payloads`（默认 2）条保全文；system prompt、grounding payload、
   assistant 决策轨迹、steer/nudge 注入**永不触碰**；observation summary 单条 2k 上限。
2. **真尺子**：
   - `context.model_context_windows`（模型名/provider → 真窗口），
     `resolve_context_window` 按 模型名 > provider > 全局默认 解析；
   - `BudgetController.record_context_observation`：provider 报的 `usage.input_tokens`
     真值覆盖该请求的压力记录，并维护 observed/estimated 的 EMA 校准因子
     （α=0.5、单次钳 [0.25, 4]）作用于后续估算。真值反馈优于换 tokenizer。
3. **压缩真缩 + hard_stop 有界自动回收**：
   - execute 每 task 起手：压力 ≥ near_limit ⇒ `slim_workspace_files` 真丢文件内容摘录
     （grounding 最重的可再生段），留路径清单 + `context_pressure_note` 说明；
   - `_budget_guard`：hard_stop 且最高压力轴为 `context_window` ⇒ 自动 compact + 续跑
     （`context_compactions` 落盘计数钉死 ≤2 次重试），仍超才 pause；
     **非上下文轴（model_calls 等）打满照旧直接 pause**；人审保底不可关。

## 3. ADR-0016 合规

- 全部三刀是预算/持久化边界的确定性处置，不替模型做任何认知判断；被丢弃的内容
  （文件摘录、旧工具输出）都**可再生**（read_file / 重跑命令），且提示明说去哪再生。
- hard_stop 自动回收不改变人审语义：它只是把「必停」推迟到「有界回收失败之后」，
  pause 仍是不可关的最后防线。

## 4. 一致性检查（Conformance）

- [x] 单测 11 条 + 真栈集成（cost_report 预置 near_limit → execute prompt 实证
  路径在/摘录不在/带说明）。
- [x] 回归护栏：既有 `test_run_command_pauses_at_budget_hard_stop`（model_calls 轴）
  不改仍绿——自动回收没有放松非上下文轴。
- [x] schema×2 + policy 模板×2 同步（`model_context_windows`、cost_report 两个新可选字段——
  旧 cost_report 无此字段仍然合法，resume 兼容）。
- [x] 快照的 `continuation_state_not_success_evidence` 语义未动（压缩不冒充成功证据）。

## 5. 明确不做（等证据）

chat 历史摘要化（Studio 侧 6×800 硬裁维持）、真 tokenizer、模型驱动摘要、
worker/context_package 路径的 droppable 应用（B2 已有 slimming）。理由见 brief §明确不做。

## 6. 回退（Rollback）

- 刀一：`history_char_budget=0` 即完全禁用（函数级参数，无 flag）。
- 刀二：`model_context_windows` 不配=全局窗口不变；删 `record_context_observation`
  调用即回到纯估算。
- 刀三：删 execute 的 slim 分支 + `_budget_guard` 的 recovery 分支即回到「快照+直接 pause」。
  三者互相独立。
