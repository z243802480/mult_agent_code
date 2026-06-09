# S74 Post-S73 Beta Convergence

## observed_pattern

成熟 agent 产品在新增编排能力后，先用真实任务校准主路径、延迟、恢复和用户叙事，再决定是否扩大默认权限。能力存在不等于产品路径已经可靠。

公开机制进一步表明，成熟 Harness 通常让模型在 `model -> tool -> observation -> model` 循环中自行推进；turns、steps、预算和 deadline 是可配置保险丝，权限与 sandbox 是硬边界。模型调用次数、repair 次数和耗时主要用于 eval、回归与产品决策，不应成为所有任务统一的硬停止条件。达到资源限制后应保留 Session 并允许恢复。

## asteria_file

- `docs/zh/研发总计划.md`
- `docs/zh/当前状态与路线.md`
- `benchmarks/vibe_slices.json`
- `tests/integration/test_execute_command.py`
- `scripts/steady_iteration_check.py`
- `benchmarks/s74_beta_matrix_gate.json`
- `scripts/beta_task_pack_check.py`
- `scripts/beta_friction_aggregate.py`

## slice_goal

在不新增编排 Wave 的前提下，完成 Post-S73 收敛：

1. 统一执行真源，关闭过期 active 计划。
2. 恢复最新主路径测试基线，优先修契约漂移而非加兼容分支。
3. 让 maintainer pulse 使用 workspace-local、可复现的临时目录和解释器。
4. 跑 3–5 个真实 Beta 任务，覆盖 session agent、subagent、L3 orchestration、显式 parallel writes opt-in。
5. 记录完成率、耗时分解、model/tool calls、repair 次数、用户进展一致性。
6. 基于证据创建下一阶段 DecisionPoint：继续维护、扩大 opt-in，或回退复杂能力。
7. 建立 Golden Tasks 配对基线；每个关键 case 至少重复 3 次，区分正确性硬门槛、产品 SLO 与资源保险丝。
8. 审计已有复杂路径；无真实收益、无 eval 或与主路径重复的实现进入冻结、合并或删除候选。
9. 愿景与实现分开裁决；参考成熟产品的稳定驾驭原语，确认当前实现劣质后保留有价值的能力契约并果断替换实现。

## do_not_copy

- 不因能力已实现就默认开启 parallel writes。
- 不为单个失败任务增加 domain keyword 分支。
- 不把 maintainer gate、route 或内部 evidence 搬到 Studio 主会话。
- 不在基线未恢复前新增 Wave 9 或新的编排层。
- 不把统一低 model-call / repair 数量写成 Runtime 硬停止条件。
- 不为满足次数指标让 Runtime 替代模型做语义决策。
- 不因单次真实任务失败或成功直接增加规则或扩大默认路径。
- 不以“自研特色”或沉没成本保护已经被 reference + eval 证明劣质的实现。

## green_checks

```powershell
pytest tests/unit/test_documentation_contracts.py -q
python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel
python scripts/beta_friction_aggregate.py --root .
```

## 2026-06-09 action-boundary correction

- Codex and Claude Agent SDK enforce permission, sandbox, network, write, and promotion risk
  before the action executes.
- Session trace, review, validation, and eval diagnose and calibrate behavior; they do not form a
  global post-hoc Runtime completeness gate.
- S74 therefore deletes RuntimeReadinessGate. Release preflight remains in gate-status, targeted
  probes inspect the target behavior directly, and irreversible boundaries remain strongly gated.

## 2026-06-09 single-session recovery correction

- Claude Agent SDK returns tool failures and denials to the same session loop; Codex review is an
  explicit change-inspection and feedback surface.
- Default Run must not create a second recovery controller by automatically invoking Review,
  Debug, Replan, or review-driven Goal policy.
- Review remains explicit and read-only with respect to orchestration: it writes verdict, evidence,
  and feedback, but does not create tasks, DecisionPoints, or AgentLoopDecisions.

## 2026-06-09 evidence-integrity correction

- Real-provider smoke, gate, and acceptance are observers, not recovery controllers.
- Timeout, partial completion, or missing review artifacts may be preserved as partial evidence,
  but must never be rewritten into synthetic eval/review/final success.
- Review follow-up keyword policies without a product consumer are deleted; major choices must
  originate from an explicit model ask or a concrete action boundary.

## 2026-06-09 product-architecture correction

- Claude Code, Codex, and OpenCode publicly converge on a continuous session plus model/tool
  loop, with permissions and deterministic controls at action boundaries.
- Plan, review, debug, modes, and subagents are explicit interactions or scoped capabilities;
  they are not evidence for a mandatory global task state machine.
- Asteria therefore treats Session Agent Loop as the product architecture. Runtime states remain
  persistence and recovery details, and Studio narrates user work rather than internal control
  objects.
- Research baseline: `docs/zh/plans/S74_REFERENCE_PRODUCT_BASELINE.md`.

## 2026-06-09 explicit recovery correction

- Claude Code returns hook/tool failures to the current model, resumes the same session, and uses
  checkpoint/rewind for session-level recovery. OpenCode treats repeated-tool doom loops as an
  approval interruption rather than a second repair runtime.
- Explicit debug may select failed work and add diagnostic intent, but it must reuse the ordinary
  Session Agent Loop, tool gateway, candidate workspace, verification, and action boundaries.
- Asteria therefore replaces the independent DebugCommand repair engine with a thin adapter over
  targeted ExecuteCommand session recovery.

## 2026-06-09 capability discovery correction

- Claude Code uses hierarchical instructions and loads focused skills when relevant. OpenCode
  exposes permitted skill descriptions and loads full skill content on demand; denied capabilities
  can be hidden from the model surface.
- Asteria therefore persists a complete CapabilityManifest for audit, but sends models a compact,
  permission-filtered discovery view. Internal role, spawn, catalog, and model-surface policy stays
  in Runtime evidence unless the model explicitly needs a scoped capability.
- Real Beta comparison must measure task outcome and latency before deleting or expanding an
  opt-in orchestration path. Batch D paired evaluation is evidence collection, not another gate.

## 2026-06-09 Batch B-D convergence result

- Accept and Resume now depend on one public SessionResultService boundary instead of calling
  RunCommand private result helpers.
- The cross-catalog manifest alignment audit was deleted. Complete manifests remain audit facts;
  task catalogs remain local dispatch facts; permission is enforced at the action boundary.
- Three current-source real-provider tasks produced one pass and two failures. Tool execution was
  not the dominant latency; provider streaming/fallback and explicit review recovery were.
- Delegation/L3/parallel writes therefore remain opt-in. The default path stays the continuous
  Session Agent Loop, and no new completeness gate or orchestration wave is justified.
