# Slice S69 — Manifest Adversarial / Verifier Steps

更新时间：2026-06-07  
依赖：S68 Workflow Monitor ✅  

## CC 机制

Dynamic Workflow 脚本内可编排 **对抗审查 subagent**；结果进 variables，merge 前强制通过。

## Asteria

| step kind | 行为 |
|---|---|
| `verifier_fanout` / `adversarial_review` | 只读 verifier worker；`verdict` 控制 pass/fail |
| `merge_checkpoint` | 要求 `verifier_gate_ok` + `merge_gate_ok` |

## green_checks

```powershell
pytest tests/unit/test_orchestration_verifier_steps.py -q
```
