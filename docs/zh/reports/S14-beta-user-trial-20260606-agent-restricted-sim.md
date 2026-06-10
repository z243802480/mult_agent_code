# S14 Beta 用户试跑 — Agent 受限模拟（v2）

日期：2026-06-06  
模式：`restricted_agent_sim`（Studio 全程，无 CLI goal 回退）

## 结果

| 项 | 值 |
| --- | --- |
| 脚本 | `studio/scripts/b6-restricted-user-sim.mjs` |
| 工作区 | `H:\beta_user_sim\workspace` |
| 总耗时 | **~3 min**（161s） |
| 结论 | ✅ **通过** |

## 路径摘要

1. `init` + starter `greet_cli.py`
2. Studio Run → 权限 Allow
3. 自动 `debug` 续跑（5 轮）至 `ready_for_accept`
4. `accept` + `pytest`（3 passed）

## 与 v1 差异

- 修复：wait 循环内 Studio `runtime-actions`（decide / resume / debug），不再 10min 超时
- `scope_expansion` 决策策略：`review_contract`（与试跑清单一致）

## 签字

> 2026-06-10 当前校正：本记录只证明受限模拟机制可运行，不能代表真人 Beta 路径，也不能驱动产品 Slice。
> 外部 Beta 签字必须来自明确标记为非维护者的真实试跑。
