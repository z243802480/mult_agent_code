# Slice S73 — Beta parallel_writes Explicit Opt-In (Wave 8)

更新时间：2026-06-07  
依赖：S72 ✅ · Wave 7 live ✅ · S70 ingress eval ✅

## CC 机制

Beta **显式 opt-in** 并行写；**非**全局默认 true。须隔离路径 + merge gate + DecisionPoint 0007。

## 交付

| 项 | 说明 |
|---|---|
| DecisionPoint | `decision-orchestration-parallel-0007` |
| Policy | `parallel_writes_beta_opt_in` + workspace `parallel_writes=true` |
| 模板默认 | `parallel_writes` 仍为 **false** |

## green_checks

```powershell
pytest tests/unit/test_orchestration_parallel_gray.py -k wave8 -q
python scripts/orchestration_wave8_beta_opt_in_probe.py --root .
```
