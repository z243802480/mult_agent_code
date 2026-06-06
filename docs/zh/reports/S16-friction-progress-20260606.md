# S16 / S17 摩擦进展 — 2026-06-06

## 目标

S16/S17 退出：B6 **连续 2 次绿**；`friction.debug` ≤2；session_agent 默认路径稳定。

## B6 试跑记录（S17 session_agent 合入后）

| # | 结果 | 耗时 | friction (decide/debug/resume) | 备注 |
| --- | --- | --- | --- | --- |
| 1 | ✅ | ~77s | 0 / 0 / 0 | S17 首轮；直达 accept |
| 2 | ❌ | ~205s | — | `execution_policy_approval` 误选 skip；`&&` 命令 blocked |
| 3 | ❌ | ~190s | — | status 推荐 replan；Studio 不支持 replan action |
| 4 | ✅ | ~164s | 0 / 1 / 0 | B6：`approve_once`；replan→resume |
| 5 | ✅ | ~244s | 0 / 1 / 0 | **连续 2 绿** ✅ |

## 本次合入修复

- **Runtime**：`session_agent` 任务强制 `serial_worker`；`serial_worker` 不再误 dispatch 到 `multi_agent`
- **Planner**：`_single_file_task` 标记 `execution_profile=session_agent`
- **B6**：`execution_policy_approval` → `approve_once`；`replan` → `resume`

## 状态

- **B6 连续 2 绿**：✅（#4 + #5）
- **doc_update dogfood**：✅（121s；decide 1 / debug 0 / resume 1）
- **friction.debug 中位数**：1（目标 ≤2）✅

## 下一步

- S17 signoff 报告
- 可选：doc_update `context_request` 低风险自动放行（减 decide 1 次）
