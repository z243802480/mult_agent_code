# Slice B6 — 模型自组织的计划可见(大重塑 Part B 前端拉齐 · 第三刀)

承 [B5](B5-guardrail-visibility.md)。B4 列的推迟清单第②条。

## 开工前先证伪:这功能是不是空气?

`model_todos.json` 在**磁盘上 4 个真实 run 里一个都没有**。所以第一件事不是画 UI,是先确认
`todo_write` 到底能不能跑通——否则就是给一个永远空的面板做界面。

**真跑一遍**(fake 模型在真 `ExecuteCommand` 路径上调 `todo_write`):

- 第一次实验 **落盘失败** → 查下去发现是**我自己的 fake 写错了键名**(契约是 `tool_name` 不是 `tool`,
  见 `core/model_driven_turn.py:44`),不是产品的问题。**别拿自己的实验错误当产品缺陷。**
- 键名修正后:`model_todos.json` **真落盘**,三条待办带状态;`allowed_tools` 里确实有 `todo_write`。

**能力是真的。缺口在可见性。**

## 真缺口(实测)

模型更新计划,在主线程上显示成一条 **"使用 todo write"** ——一条泛化的工具调用行。**模型的计划以
工具黑话的形式出现,而不是一份计划。** 同时:

- `transcript_kind="todo_update"` 在 schema 枚举里**存在,但全仓无人 emit**。
- server 端**不读** `model_todos.json`(典型 have-write-no-read)。
- `PlanChecklist` 只从 `task_plan.tasks` 派生 —— 规划器一开始定的**静态**清单;
  `runtime_progress.todo` / `todo_view` 在整个 `studio/src/` **零引用**。

后果:**模型在按自己的清单干活,用户看到的却是规划器一开始画的另一张清单。**

## observed_pattern(行业已验证)
**Claude Code 的 TodoWrite**:模型的 todo 列表**就是**计划面本身,原地更新;那次工具调用**从不**
作为 raw tool row 出现在对话里。计划是产物,不是"它调了个工具"这件事。

## asteria_mapping(怎么做)

### 后端(Triage Lock 合规:append user_progress only)
- `TodoWriteTool` 的返回 `data` 补 `update_reason`(此前只有 path/item_count/items ——
  **"为什么改计划"这个模型自己的话根本传不出来**)。
- `_record_model_driven_event` 的工具观察分支:`tool_name == "todo_write"` 且成功 → 除既有的
  Inspector 证据行外,**另发一张主线程 `todo_update` 卡**(items + 模型自己的 reason)。
  **子专家的 todo 是它自己的便签、不是主脑的计划** → 仍留 Inspector(`not is_child`)。

### 前端
- server 补读 `model_todos.json` → `payload.model_todos`。
- `derivePlan` 改双源、**模型的清单优先**:`model_todos` → 回退 `task_plan`。
  **这不是 UI 自创的第二意见** —— 后端 `todo_read` 本来就是这个优先级(`model_todos` → `task_plan`),
  前端照抄同一套真源。
- `PlanChecklist` 显示 `updateReason`(静态计划永远没有这个:它不会改主意)。
- **raw 的 "使用 todo write" 工具行挡出主线程**(按结构标记 `data.tool_name`,不靠标题文本):
  同一件事显示两次、其中一次还是黑话。调用本身仍留 Inspector。

## Definition of Done
- 真跑 `todo_write` 的 run:`model_todos.json` 落盘 + 主线程出现带 items/reason 的 `todo_update` 卡。
- vitest 锁:模型清单优先于 task_plan、无 todo 时回退、空清单也回退、无计划时**不画假壳**、
  raw 工具行被挡、`todo_update` 卡本身不被误挡。
- pytest 全绿 + mypy 棘轮零新增债 + studio lint 0 error + build + 真 smoke。

## 顺手修的东西(重要)
**B5 里一条 vitest 断言是空过的**:它调 `toNarrativeEvents` 去验"不被脚手架过滤器吞掉",而过滤器
(`isInternalLoopScaffolding`)其实挂在 **`buildRunNarrative`** 上 → 那条断言恒真、什么都没验。
已改用 `buildRunNarrative`。**空过的测试比没有测试更坏 —— 它给你假的安全感。**

## 后续(承 B4/B5 推迟清单)
① 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary` / 重复内容浪费)
② 专家成本进汇总(child 不过 `worker_recorder`)
③ 守门哑区(规划器给 prose 占位符而非路径时,续跑守门无从检查)
