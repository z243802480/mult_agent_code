# ADR-0018：发布 gate 判据锚定真实代码正确性（取代纯结构场景计数）

- 状态：Proposed（2026-07-05）
- 关联：[研发总计划 §16.1 line 467]、[ADR-0016 认知归模型/边界归状态]、`correctness_eval_command.py`、`gate_status_command.py`
- 解锁：2026-07-04/05 用户明确授权解锁 DO_NOT_TOUCH 的 acceptance/gate 栈以做"真代码正确性 eval gate"。

## 1. 背景（Context）

`gate-status` 的发布终态 `ready_for_small_real_task_validation` 此前**仅**凭三关的结构布尔达成：
`real_model_gate.ok` → `validation.ok/validation_ready` → `core.ok`（`gate_status_command.py::_stage`）。
这三个 `ok` 来自 acceptance 场景的**通过计数**（结构指标），**不消费**每个 run 已经记录在
`tool_calls.jsonl` 里的真实 `run_tests`/`run_command` 退出码。后果：一个 run 可以"每个场景结构上
都过、`ok==True`"，但其真实可执行验证其实在失败——gate 仍判 `release_ready`。这正是研发总计划
§16.1 line 467 要闭的"**真代码正确性 eval gate（取代 UX 结构指标）**"缺口。

真实信号早已存在：`CorrectnessEvalCommand.score_signal(run_dir)` 读持久化证据，返回
`{status, score, reason}`，`score = run_tests/run_command 实际通过比例`（非 0.9/0.6/0.2 状态桶），
且**无可执行验证时返回 `None`**（诚实不伪造）。review 管线已消费它（`review_command.py:191`）；
gate 尚未。

## 2. 决策（Decision）

在 `gate_status_command.py::run()` 的既有"后置降级 guard 链"（route/model_call/promotion/plugin
已是同一 idiom）末尾**新增一条 guard**：

- 出 `ready_for_small_real_task_validation` 时，用新 helper `_acceptance_correctness(validation, core)`
  扫每个 acceptance report 的 `scenarios`，由 `workspace + summary.run_id` 复用既有 `_scenario_run_dir`
  定位 run_dir，`score_signal` 分级，取**跨场景最差**信号。
- 若最差信号 `is not None and status != "pass"` → 降级 `stage = "acceptance_correctness_failed"`
  （`_release_state` 归入 blocked → `release_ready=False`、`blocking_reason` 给出真实原因）。
- 若为 `None`（无任何可执行验证证据）→ **不阻塞、不伪造**，但把 `acceptance_correctness`
  透出到 `to_dict()` 供人可见（诚实呈现"未验证"而非编造通过）。

判据来源改为**真实退出码**，不再只是结构 `ok`。不引入 flag：这是让 gate 对**真实失败证据**更严的
诚实修正，不改变自主行为——用 flag 关掉"诚实"是反语义的（回退方式见 §5）。

## 3. ADR-0016 合规

- **§1 认知归模型**：本 guard 不做任何认知/规划判断，只把模型/工具已产生的**客观退出码证据**汇总为
  gate 判据；不是新状态机分支里的"聪明推断"。
- **§2 边界归状态**：发布准入是确定性人审边界，本就属显式状态层；把它锚定到**可审计的真实证据**
  而非结构计数，是强化边界的确定性，符合"边界归状态"。
- **§3 反伪造标量**：核心动机即消除"结构 `ok` 冒充代码正确"的伪造。用真实 pass-rate；`None` 时
  **拒绝伪造**（既不伪造 pass 也不伪造 fail），与 `score_signal` 契约一致。

## 4. 一致性检查清单（Conformance）

- [x] 判据取自持久化 `tool_calls.jsonl` 真实退出码，不再新增伪造标量。
- [x] `None`（无可执行验证）不被强判为 pass 或 fail，仅透出可见。
- [x] 只在真实证据"非绿"时降级；无证据/证据绿时零行为变化（既有 79 gate 测试全绿）。
- [x] 新增正向测试证明"结构过但真验证挂 → gate 降级 blocked"。
- [x] 未触 `correctness_eval_command.py` / `real_model_gate.py` / `real_model_acceptance.py`
  （只读消费）；不改 schema（沿用 `eval_report`，无新持久化字段）。

## 5. 回退（Rollback）

移除 `run()` 中的 `_acceptance_correctness` guard 子句（及数据类/`to_dict` 的 `acceptance_correctness`
字段）即完全回退到纯结构判据。无 flag、无 schema 迁移、无持久化格式变化，回退零成本。

## 6. 后续（低优先）

- 是否把 `partial` 与 `fail` 区别对待（当前一律非 `pass` 即降级，release 从严）——若真实 acceptance
  运行出现"预期非零退出的负向测试"误伤，再引入按场景意图标注。
- Studio 侧把 `acceptance_correctness` 透到 gate 面板（maintainer 视图），与其它 gate 证据并列。
