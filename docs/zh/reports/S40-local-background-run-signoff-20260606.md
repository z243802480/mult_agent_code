# S40 Local Background Run — Signoff 2026-06-06

## 目标

闭合 Phase 6 **本地 background run**：subprocess 启动 goal、registry 持久化、status/Studio 徽章投影；**defer 真 cloud VM**。

## 交付

| 项 | 证据 |
| --- | --- |
| `local_background_run.py` | registry · spawn · refresh · `background_run.json` 证据 |
| CLI | `asteria background start/status/list` · `goal --background` |
| status 投影 | `background_runs` on `status --json` |
| Studio | `readBackgroundRuns()` · Inspector `BackgroundRunPanel` |
| 闸门 | `phase6f_local_background_run_gate.json` |

## green_checks

```powershell
pytest tests/integration/test_phase6f_local_background_run_gate.py -q
pytest tests/unit/test_local_background_run.py -q
pytest -q
```

## 纪律确认

- 未建第二 runtime
- DO_NOT_TOUCH `run_command` / `execute_command` 大 refactor
- cloud VM **defer**

## 波段状态

**Phase 6 Long Horizon（S37–S40）** 四 slice 均已落地。
