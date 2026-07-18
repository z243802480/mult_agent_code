# S90 — 对话/上下文管理：压缩真缩 + 真尺子 + 循环历史微压缩

## 用户拍的板（2026-07-18）

「还有对话管理吧。应该是跟记忆管理一样重要的吧。包括中间的压缩对话功能」→ 诊断后
「按你建议进行完善修复吧」。刀四（chat 历史摘要化）显式排除：Studio 侧、等真 friction 证据。

## 出发点（调查坐实的现状）

- **结构性好消息**：执行循环不是无限长对话——每 task 从零播种 messages（≤12 轮保险丝）、
  grounding 每 task 从持久化产物重建 ⇒「对话越跑越长」被结构圈住。
- **债（completion-reaudit-20260718 §3 第 3 条）**：「压缩」只写快照**从不缩活提示**；
  `_compact_boundary` 算出 preserve/droppable 无人应用；0.9 hard_stop 直接 pause 等人
  （与 set-and-forget 产能观直接冲突）。
- payload 单条有 6KB `_clip` 上限，但**累积总和无界**；observation summary 无长度上限。
- token 计量=字符启发式（CJK=1、其他 ÷4），窗口全局硬编码 200k **不随 provider 变**——
  真窗口更小的模型（glm/minimax 栈）的 0.75/0.9 阈值量在虚构天花板上。

## 主流对标（机制学习）

- Claude Code auto-compact / microcompact：到阈值自动摘要**旧工具输出**原地续跑，
  近几轮保留全文，pause 只是最后防线。→ 刀一 + 刀三。
- 各家 harness 的 usage 回报闭环：provider 报的真 prompt tokens 优于任何估算。→ 刀二。
- **刻意不抄**：模型驱动的对话摘要。本仓 grounding 是确定性重建的，压缩的正确形态是
  **段级丢弃 + ActiveGoalMemory/记忆索引兜底语义**（S89 刚修好，正是压缩的安全网）；
  确定性丢弃归状态层（ADR-0016），模型摘要环节会引入虚构风险，等证据。

## 三刀落点

1. **循环历史微压缩**（`model_driven_turn.py`）：`history_char_budget=60k` 字符，超了就把
   **最旧** observation 消息的 payload 坍缩成摘要（带「如何再生」提示），最近
   `keep_recent=2` 条保全文，system/grounding/assistant 决策轨迹永不触碰；observation
   summary 单条加 2k 上限。确定性、可再生（全文仍在 run evidence）。
2. **真尺子**（`context_budget.py` + `budget.py` + `metered.py`）：
   - `context.model_context_windows`（模型名/provider → 真窗口）+ `resolve_context_window`
     （model > provider > 全局 200k 回落）。schema×2 + 模板×2 同步。
   - `record_context_observation`：每次响应后把 `usage.input_tokens`（provider 真值）写回
     压力信号（覆盖该请求的估算记录）+ 维护 observed/estimated 的 EMA 校准因子
     （α=0.5，单次钳 [0.25,4] 防疯狂回报毒化），未来估算先乘因子再算压力。
     cost_report 新增两字段（可选，旧报告兼容）。
3. **压缩真缩 + hard_stop 有界自动回收**：
   - execute 每 task 起手：压力 ≥ near_limit ⇒ `slim_workspace_files` 把 grounding 里最重
     且可再生的段（文件内容摘录 20×1200）真丢掉，只留路径清单+说明（防重复建文件靠的是
     清单不是摘录）——droppable 哲学第一次被**应用**到活提示。
   - `run_command._budget_guard`：hard_stop 且最高压力轴是 `context_window` 时，先自动
     compact+瘦身续跑（`context_compactions` 计数器钉死 ≤2 次），仍超才 pause；
     **其他预算轴（model_calls 等）打满照旧直接 pause**——瘦身对它们无意义。
     人审保底不可关（beta_safe 教训：可关的安全守卫等于没修）。

## 验收

1. 单测 11 条：微压缩坍缩旧 payload/最近保全文/预算内 no-op；per-model 窗口三级回落；
   校准 EMA/钳制/往返持久化；slim 函数；guard 三分支（context 轴回收/回收上限后 pause/
   非 context 轴照旧 pause）。
2. **真栈集成**：cost_report 预置 near_limit → execute 的 prompt 实证「路径在、摘录不在、
   带 elision 说明」（`test_context_injection.py`）。
3. 回归护栏：既有 `test_run_command_pauses_at_budget_hard_stop`（model_calls 轴打满）
   **不改仍绿**——证明自动回收没有放松非上下文轴的 pause。
4. 全量 pytest + ruff + mypy_ratchet exit 0。

## 明确不做（本刀）

- chat 历史摘要化（6×800 硬裁维持现状）——Studio 侧、等被咬到的真实证据。
- 真 tokenizer——校准因子已把系统性漂移收敛掉，tokenizer 依赖每个 provider 的私有实现，
  性价比低；真值反馈是更诚实的路。
- 模型驱动摘要——见主流对标。
- worker/context_package 路径的 droppable 应用——B2 已有 slimming，等证据再对齐。
