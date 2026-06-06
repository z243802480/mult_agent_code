# 文档整理与清理计划

**日期**：2026-06-06  
**触发**：Phase 6 闭合 + Phase 8 启动；三源文档与多份 holistic 计划出现 **ACTIVE/⏳ 过时** 表述。

---

## 1. 原则（与 [`文档导航.md`](../文档导航.md) 一致）

| 类型 | 动作 |
| --- | --- |
| **三源真源** | `研发总计划` · `当前状态` · `AGENTS` + `vibe_slices.json` — **必须同步** |
| **reports/** | **不删** tracked 签字；只更新索引 |
| **plans/ 已闭合波段** | 移入 `archive/plans/`，文首加「非当前依据」 |
| **plans/ 活跃** | 仅保留 S41–S44 + 框架 RFC |
| **archive/** | 只读追溯；不再写入新过程计划 |
| **RFC 过时门槛** | 实现已落地 → 改状态为「已实现」，不删文件 |

---

## 2. 本轮已执行（2026-06-06）

- [x] 新增 [`LONG_TASK_GOAL_FRAMEWORK.md`](./LONG_TASK_GOAL_FRAMEWORK.md) — 长任务三层目标 + Claude 对标
- [x] 重写 [`NORTH_STAR_RFC.md`](./NORTH_STAR_RFC.md) 为「已实现」摘要
- [x] 精简 [`当前状态与路线.md`](../当前状态与路线.md) §4（删除轨道 D 过时 ACTIVE）
- [x] 修正 [`研发总计划.md`](../研发总计划.md) §3 / §8 过时 ACTIVE
- [x] 更新 [`文档导航.md`](../文档导航.md) — Phase 8、reports 索引、plans 分层
- [x] 闭合 holistic 计划移入 [`archive/plans/`](../archive/plans/)
- [x] 更新 [`deferred/SWARM_SANDBOX_RFC.md`](../deferred/SWARM_SANDBOX_RFC.md) S34 状态

---

## 3. 后续批次（按需）

| 批次 | 内容 | 优先级 |
| --- | --- | --- |
| B1 | `产品规格.md` §长任务 与框架交叉引用（不扩 scope） | P2 |
| B2 | `大模型循环与动态上下文设计.md` 增 §长任务 链接 | P2 |
| B3 | `archive/` 内重复竞品调研 → 仅保留带 banner 的一份 | P3 |
| B4 | reports 索引自动生成（optional script） | P3 |
| B5 | Phase 8 闭合后移 `asteria-holistic-S41-S44.md` → archive | S44 后 |

---

## 4. 验收

```powershell
pytest tests/unit/test_documentation_contracts.py -q
```

三源 `ACTIVE_SLICE` / `ACTIVE_PHASE` 一致；导航可链到所有 **现行** plans 与框架文档。
