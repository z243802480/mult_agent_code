# 主对话区 = Agent-Loop 视图：主流调研 + 设计判据（2026-07-05）

> 触发：用户指出主区被当成"多轮 chat"在做，实则我们是 **agent loop**（一个 goal → 自主多步
> 过程 → 可验证交付物）。核心原则（用户原话）：**工作过程对用户必须"可控 + 可读"**，否则全在
> 后台跑、用户不知情 = 不可用。本文沉淀 8 个主流产品的调研结论与我们的落地判据。

## 1. 调研对象与来源

Claude Code、Devin(Cognition)、Manus、Cursor、Windsurf/Cascade、GitHub Copilot(Agent/Workspace/
Cloud)、Replit Agent、Lovable、Bolt.new。经各自官方文档 + changelog + hands-on 复核。

## 2. 意图路由（关键纠偏）

**并非一边倒自动路由。** 分两派：

- **纯自动路由**：Claude Code(CLI 无模式选择器·纯自然语言·模型自决工具)、Manus(Adaptive 自动选
  Chat/Agent)。
- **手动模式切换 + 软 auto-suggest（IDE agent 主流）**：Cursor(模式下拉/Shift+Tab·Plan 软建议)、
  Copilot(Ask/Edit/Agent 下拉·不自动检测)、Windsurf(Code/Chat 切换 + Planning 自动激活)、
  Devin(Ask/Agent 切换)、Replit/Lovable/Bolt(Plan/Build 切换)。

**共识**：默认就是自主模式，切换器是给**少数只读/计划**场景兜底；用户唯一普遍显式控制的是
**权限档**（安全 dial），不是意图。

**我们的判据**：`Auto` 默认 + `intent-router.mjs` 已分类(chat/plan/run) + `/` 斜杠可覆盖 →
用户**本就没被强迫选 goal**，已满足"智能体自决"。**不删模式选择器**（删了反背离 IDE agent 主流），
保持 Auto 默认、模式为紧凑次级控件。权限档保留可见（全产品普适）。

## 3. Loop 可读性（普适四原语）

1. **计划/todo = 持久自勾选脊梁**（最强共识）：Claude Code todos(pending/in_progress/completed·
   activeForm 现在进行时标签)、Manus `todo.md`(每步勾掉·完成 gate)、Cursor/Windsurf 结构化 todo
   (依赖·可重排·inline)、Copilot plan agent + background todo agent、Replit 任务表。
   → 我们有 `PlanChecklist`+`derivePlan`(读真实 task_plan)，**须持久放主位**(已恢复 f087377)。
   缺：现在进行时 activeForm 标签(后端 task 无此字段·待补或客户端派生)。
2. **步骤轨迹可读**：主线高层人话摘要 + 可折叠细节(Copilot 折叠工具行·Lovable Details 视图·
   Cursor 折叠步块·Manus 一步一动作)；思考**摘要而非原文**(Claude Code v2 折叠·Ctrl+O 展开)。
   → 我们有 TurnMiddle 折叠 + ThinkingBlock，方向对；须把步骤 title 人话化(去黑话)。
3. **逐文件/逐块 diff 审阅**：Cursor "Review changes" 面板 + per-hunk、Windsurf diff zones 绿/红
   per-hunk accept/reject、Copilot Keep/Undo、Bolt 外科手术 diff。
   → 我们有文件卡→diff、Accept/Revert per-file；**per-hunk 是后续增强**。
4. **checkpoint / 回滚**：Claude Code 双 Esc rewind、Cursor 聊天时间线快照 restore、Copilot
   Restore Checkpoint、Windsurf per-step revert、Replit 双向时间旅行、Bolt version history。
   → 我们有 `TurnRewindButton`；可对齐"时间线快照"表达。

## 4. 运行中可控

- **停**：Esc/Stop（我们有 Stop）。
- **插话 steer**：主流分两式——Claude Code/Devin/Manus **打字即插话重定向(不停)**；Copilot 显式
  "Stop and Send" vs "Steer with Message"；Cursor Enter 排队 / Cmd+Enter 立即。→ 我们现在是**排队**
  (isRunning 时入队)，可增强为"插话 steer"。
- **计划审批 checkpoint**（大任务先批准再执行·常与计费挂钩）：Devin(ACU 前 Interactive Planning·
  cited files+snippets)、Replit(Accept tasks/Revise·仅批准后计费)、Bolt("Implement this plan")、
  Copilot Workspace(Task→Spec→Plan→Implementation 每级可编辑)、Claude Code plan mode(批准才编辑·
  Ctrl+G 编辑计划)。→ 我们有 plan 模式；**计划审批门是高价值后续**。

## 5. 可读 vs 黑箱（用户第一诉求）

Manus 明确把常驻实时面板定位为破"黑箱"。普适可读要素：计划可见、步骤可见、diff 可见、
交付物+验证可见、异步跑有完成通知。**反例(该避免)**：Copilot Agent 自动落编辑不预审(仅危险命令
gate)、工具默认折叠、Autopilot 静默——可读性成了用户可关掉的取舍。

## 6. 我们主区的目标形态（单 goal loop 视图）

```
[目标]  ← 一次，顶部
[计划脊梁]  PlanChecklist 持久·逐项 done/in_progress/blocked/pending·(补 activeForm 现在进行时)
[阶段]  Understand→Plan→Execute→Review→Done，仅运行中
[步骤流]  人话摘要 + 可折叠细节；思考折叠
[交付]  文件卡(可点 diff) + ✓ 验证 + 一句收尾 recap
[控制]  运行中 Stop + 打字 steer；完成后 审阅/接受 diff；rewind 回滚
[输入]  一个输入框，Auto 默认(intent-router 分类)，权限档紧凑可见，/ 斜杠覆盖
```

**关键认知**：我们**大多原语已具备**（计划清单、折叠步骤、文件卡、rewind、权限档、Stop、队列），
瓶颈一直是**呈现/主次**，不是缺功能。redesign = 把 loop 叙事摆正，不是造新引擎。

## 7. 已落地 / 待办

- 已落地：答案优先(351e7df)、去顶部 token 遥测、结论人话化、文件卡露出、recap 根治(8206a06)、
  计划脊梁恢复持久(f087377)。
- 待办(按价值)：①步骤 title 人话化去黑话 ②activeForm 现在进行时 ③计划审批 checkpoint
  ④打字 steer(替代纯排队) ⑤per-hunk diff 审阅 ⑥用**干净单 goal 真跑**边做边对齐(不再累积会话瞎测)。

## 来源

见各子代理调研原文（本会话）：Claude Code(code.claude.com/docs)、Devin(docs.devin.ai)、
Manus(help.manus.im·manus.im/blog)、Cursor(cursor.com/docs·changelog)、Windsurf(docs.windsurf.com→
docs.devin.ai)、Copilot(code.visualstudio.com/docs·github.blog·githubnext)、Replit(docs.replit.com)、
Lovable(docs.lovable.dev)、Bolt(support.bolt.new)。
