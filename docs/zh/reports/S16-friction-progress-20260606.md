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
- **doc_update dogfood**：✅（152s；**friction 0/0/0** — context_request 自动放行）
- **Phase 5 蜂群 RFC**：✅ 扩展 [`SWARM_SANDBOX_RFC.md`](./deferred/SWARM_SANDBOX_RFC.md)（harness 分层 + S18–S21 里程碑）
