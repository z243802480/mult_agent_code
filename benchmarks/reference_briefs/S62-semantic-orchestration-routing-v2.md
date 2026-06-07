# Slice S62 — Semantic Orchestration Routing v2

更新时间：2026-06-07  
状态：**active · S62-1/2/3/4/5 ✅ · model+strong**  
依赖：S61 R0–R5 · Studio orchestration hook  
哲学：[`docs/zh/plans/RUNTIME_MULTI_DISPATCH_MODEL.md`](../../docs/zh/plans/RUNTIME_MULTI_DISPATCH_MODEL.md) §8

## 架构原则（2026-06 收束）

```text
抉择类（路由、GoalSpec、Plan、Review）→ strong 模型 + capability catalog
机械类（summarization、批量分类、重复抽取）→ cheap/medium（非 orchestration）
程序层（显式 mode、available 约束、权限/预算/merge）→ 确定性护栏
keyword NLU 快路径 → 已移除；rules 模式仅 maintainer/CI
```

对标 CC/Cursor：**语义路由由 strong 模型读 catalog 完成**，不靠 keyword 假装理解用户。

## observed_pattern（行业 · 2026-06）

| 产品 | 编排模式 | Asteria 对齐 |
| --- | --- | --- |
| **Claude Code** | 主 loop 模型 turn-by-turn 选 plan/tool/subagent | strong route + AgentLoopDecision |
| **Cursor** | 模型读 tool/agent 描述选路径 | RuntimeOrchestrationCatalog |
| **Asteria** | `orchestration_router: model` · tier 固定 strong | ✅ 默认 |

## asteria_mapping

| 交付 | 状态 |
| --- | --- |
| Strong 语义 route（默认） | ✅ |
| 显式 Studio mode → capability（非 NLU） | ✅ |
| route-worker + Studio 缓存 | ✅ |
| orchestration_routes.jsonl 证据 | ✅ |
| rules 模式（CI/maintainer only） | ✅ |
| hybrid keyword 快路径 | ❌ 已删除 |

## 子阶段

| ID | 交付 | 状态 |
| --- | --- | --- |
| S62-1 | 路由证据 + Chat prompt | ✅ |
| S62-2 | route-worker + slim IPC | ✅ |
| S62-3 | orchestration_route_pulse + triple_track | ✅ |
| S62-4 | golden cases + real-model route eval | ✅ 90% / 10 cases |
| S62-5 | chat→execute handoff（strong 二次 route + chat 上下文） | ✅ |

## do_not_copy

- keyword 意图路由作为生产默认
- cheap 模型做 orchestration 抉择
- domain if/else 执行分支

## green_checks

```powershell
pytest tests/unit/test_orchestration_router.py tests/unit/test_route_worker.py -q
python scripts/orchestration_route_pulse.py --root .
python scripts/orchestration_route_pulse.py --root . --real
node studio/scripts/orchestration-route-worker-smoke.mjs
node studio/scripts/chat-execute-handoff-smoke.mjs
```
