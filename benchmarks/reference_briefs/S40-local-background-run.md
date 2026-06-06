# Slice S40 — Local Background Run

## observed_pattern

- 长任务需要 durable background execution；Studio 显示运行徽章，CLI 可 detach/resume。
- 真 cloud VM background **defer**；MVP 用本地 subprocess + 状态持久化。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| local subprocess wrapper | durable run 状态 `.asteria/runs/` |
| Studio 徽章 | runtime evidence 只读投影 |
| `phase6f_local_background_run_gate.json` | Phase 6 wave 6 闸门 |

## do_not_copy

- 不建第二 runtime
- 不默认 cloud 依赖

## green_checks（规划）

```bash
pytest tests/integration/test_phase6f_local_background_run_gate.py -q
```

## discipline

- defer 真 cloud VM 至 Phase 7+
- DO_NOT_TOUCH execute_command / run_command 大 refactor

---

## 实现记录（2026-06-06）

| 交付 | 路径 |
| --- | --- |
| registry + spawn | `local_background_run.py` |
| CLI | `asteria background start/status/list` · `goal --background` |
| status 投影 | `background_runs` on `status --json` |
| Studio 徽章 | `readBackgroundRuns()` · Inspector `BackgroundRunPanel` |
| 闸门 | `phase6f_local_background_run_gate.json` |

签字：`docs/zh/reports/S40-local-background-run-signoff-20260606.md`
