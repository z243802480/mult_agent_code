# S16 摩擦收敛进展 — 2026-06-06

## 目标

S16 退出条件：B6 连续 2 次绿；`friction.debug` 可接受（≤2）；三源文档一致。

## B6 试跑记录

| # | 结果 | 耗时 | friction (decide/debug/resume) | 备注 |
| --- | --- | --- | --- | --- |
| 1 | ✅ | ~176s | 0 / 1 / 0 | 首次绿；无 decide |
| 2 | ❌ | ~622s | — | `in_progress` 空转超时 |
| 3 | ❌ | ~205s | — | decide 后 `status --debug` 未识别 |
| 4 | ❌ | ~248s | — | `repair_limit` 决策误选 `manual_review` |

## 已合入修复

- Harness：低风险 / benign scope 自动放行
- Studio：runtime_request decide 后自动 resume
- B6：`friction` 指标；`status --debug` → debug；`repair_limit` → `create_repair_task`；停滞 nudge resume

## 下一步

- 再跑 2 次 B6 验证连续绿
- `python scripts/s16_doc_update_dogfood.py --repo . --fresh` 复验任务包 2
