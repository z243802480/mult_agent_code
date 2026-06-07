# Slice S55 — Harness friction II（轨道 H）

更新时间：2026-06-06  
状态：**✅ 已签字**  
依赖：S54 · S17 session_agent  
计划：[`docs/zh/plans/TRIPLE_TRACK_MAINT_PLAN.md`](../../docs/zh/plans/TRIPLE_TRACK_MAINT_PLAN.md)

## 0. 调研结论（2026-06-06）

依据 S16 B6 记录、S54 基线、代码路径核对：

| 摩擦源 | 证据 | 对策 |
| --- | --- | --- |
| `scope_expansion` → decide 卡 | `tests/test_*.py` 未算 benign → 无法 auto_apply | **扩展** `is_benign_workspace_scope` |
| `execution_policy_approval` | B6 #2 误选 skip | Studio **approve_once** 引导文案 |
| `debug`/repair 循环 | maintainer-smoke 3× repair；B6 debug≤2 目标 | Thread **runtimeNextStepSummary** |
| `context_request` | doc_update 0/0/0 — 已有 auto_apply | 不动 |
| Studio replan | S33 已 map → continue | 不动 |

## 1. 目标

Beta 主路径 friction 来自 **decide / debug / repair**，不是缺 Studio 面板。本 slice 减认知负担、提高可观测性。

| # | 交付 | 成功标准 |
| --- | --- | --- |
| H1 | 决策卡引导 | runtime_request / scope / context 卡有用户向 hint；Review contract 后 server 自动 resume |
| H2 | repair 叙事 | Thread Next action 对 repair_limit / debug 有可读文案 |
| H3 | 重复性脉搏 | B6 或 friction contract 绿；`friction.debug` 目标 ≤2 |

## 2. 非目标

- 新 Studio 大面板（属 F2 friction 驱动）
- execute/run 重构（DO_NOT_TOUCH）

## 3. green_checks

```powershell
pytest tests/unit/test_documentation_contracts.py tests/unit/test_friction_contract.py tests/unit/test_runtime_request_helpers.py tests/unit/test_harness_repeatability_pulse.py -q
node studio/scripts/decision-guidance-smoke.mjs
python scripts/harness_repeatability_pulse.py --root .
python scripts/triple_track_pulse.py --root . --skip-b6
```

## 4. 验收

- [x] H1 决策 hint + smoke（含 execution_policy 文案）
- [x] H2 runtimeNextStepSummary（debug/repair/decide 叙事）
- [x] H3 harness_repeatability_pulse（B6 可选 `--with-b6`）
- [x] Runtime：`tests/test_*.py` benign scope → 减 decide 摩擦
