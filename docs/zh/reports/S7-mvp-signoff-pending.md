# S7 MVP 签字记录（待完成）

**状态**：pending — 需本地 real provider 与 `small_code_change` E2E  
**ACTIVE_SLICE**：S7 → 签字后进入 Phase 3 / S8 收尾  
**契约 CI**：`pytest tests/integration/test_s7_golden_benchmark.py -q`（fake fixture，**不代替**本签字）

## 环境

| 项 | 值 |
| --- | --- |
| workspace | `<填写>` |
| run_id | `<填写>` |
| 日期 | `<填写>` |
| 操作者 | `<填写>` |

## Checklist（来自 `benchmarks/phase2_mvp_gate.json`）

- [ ] `python -m asteria_runtime model-check --root <workspace> --tier medium --json` 通过
- [ ] `python -m asteria_runtime model-check --root <workspace> --tier strong --json` 通过
- [ ] 执行 `small_code_change`（见 `benchmarks/studio_user_tasks.json`）
- [ ] `python -m asteria_runtime studio-benchmark --root <workspace> --run-id <run_id> --json` score ≥ 0.8
- [ ] （可选）`python -m asteria_runtime evidence-bundle --root <workspace>`

## 结果摘要

```text
studio-benchmark score:
model-check medium:
model-check strong:
备注:
```

## 签字后动作

1. 将本文件重命名为 `S7-mvp-signoff-YYYYMMDD.md` 并勾选 checklist  
2. 更新 `AGENTS.md` / `vibe_slices.json`：`ACTIVE_SLICE` → S8，`ACTIVE_PHASE` → Phase 3  
3. 更新 `docs/zh/当前状态与路线.md` §5 闸门为 Phase 2 已通过  
4. 执行 Phase 3：rolling scoped real cases、`test_user_command_smoke.py` 扩展
