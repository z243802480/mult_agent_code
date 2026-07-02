# S76 — Studio 前端产品化（对标竞品 · I1–I14 · 5 轮 /goal 驱动）· Signoff

- 日期：2026-07-03 · ACTIVE_PHASE：Post-S73 Beta convergence · ACTIVE_SLICE：S76（承接 S75）
- 触发（逐字）：用户对真跑贪吃蛇后「前面 thinking 了半天，没崩一个字，最后弹了个 review……怎么感觉还是状态机那一套」→「主窗口内容区需要详细设计、人性化、可视化零缺陷、长任务不崩、session 备份还原」→ `/goal`「把整个前端 UX 结合项目用途往前迭代 5 轮，前后端搭配、修缺陷、更新文档，更好用更健康」。
- 路线真源：[`docs/zh/前端产品化路线.md`](../前端产品化路线.md)（12 代理竞品对标 workflow + 5 维现状审计 → I1–I14）。

## 1. 根因（3 路 workflow + 本人复核，非猜测）

后端**是真·大模型循环**（真调 minimax/glm，产出可玩 snake-game.html，96 真 token delta 含 `<think>`）。观感崩在**前端主区渲染选择**：会话自有富事件因 run_id 不匹配被换成 `runtimeSessionEvents` 粗事件，后者丢掉所有无 `transcript_kind` 的 token delta → 只剩阶段标签+final。次因：完成即删思考、过程折叠、乱码来自粗回退 goal_spec。

## 2. 交付（逐迭代真数据核实，一迭代一 commit，未推）

| 迭代 | 内容 | 核实 |
|---|---|---|
| I1 | 主区活起来：优先自有富事件（修根因+乱码）+ 思考常驻"Thought for Xs"芯片 + 工具卡常驻 + 工作区切换解卡 | snake 会话流式推理+正确中文 |
| I2 | 发送/决策失败 toast+Retry（不再静默）+ SSE live/reconnecting/offline pill + 指数退避重连 | build+pill 正常隐藏 |
| I3 | phase 条(understand→…→done 只点亮到达) + plan 清单(派生真 task_plan，○◐✓⚠，无则不显) | phase 全亮+"Plan 1 of 1"+真任务 done |
| I4 | context/token 表：`cost_report` 派生 "N% · used/window · in/out (est.)"，>0.75 橙，无 $ | "4% context · 8.6k/200k · 9.3k in · 6.8k out (est.)" |
| I5 | `cleanReasoning` 全路径剥 `<think>` + 流式 caret | 芯片/final 无回归 |
| I6 | per-session 事件缓存（切回即时恢复不闪空重取） | A→B→A snake 即时恢复 |
| I7 | turn 窗口化(最近 60+load earlier) + 跳到最新 pill + 尊重手动上滚 | 2-turn 无回归、控件按条件隐藏 |
| I9 | 运行中排队(queued 芯片，run 结束按 turn 边界自动发) + Esc 停 | 空闲态无回归 |
| I12 | 未知错误不再空白→真首行(脱敏)+下一步 + auth/rate/timeout/network/model 分类徽章 | 成功 run 无徽章 |
| I13 | 命令面板 Ctrl+K：切会话(模糊)+Review/面板/设置/刷新/停，全键盘 | 开→7 命令→关 |
| I14 | 浅色主题跟随 OS（重映射全 token，data-theme=dark 退回） | preview_resize light 全surface干净翻转无泄漏 |

**缺陷修复**：① `redact()` key 正则 `token` 误伤 `*_tokens` 计数字段→`isSecretKey` 白名单排除遥测、仍红真凭证（context 表因此显真 token）；② 完成 job 从不清 `liveJobs`→`liveJobs.size>0` 永久卡"切换工作区"→改按真正 running 判定（已重启生效）；③ session↔run 粗回退 + 乱码 goal 标题（I1 顺带）。

## 3. 全量健康

- studio：`tsc --noEmit` + `vite build` 逐迭代绿；thread smokes（session-main-path/chat-stream-final/user-thread-copy/plan-output）+ intent-router + permission-level 全过。
- **修 1 处回归**：`session-main-path-contract` 硬匹配 `"{turns.map"` 字面量，I7 改名 `visibleTurns.map` 后失配→改匹配稳定标记 `.map((turnSteps`（行为未变，turns 仍在 RuntimeSnapshot 前）。
- 未触 Python / DO_NOT_TOUCH（execute/run/gate/acceptance）；后端仅动 `studio/server.mjs`。
- 真数据核实全程在 `H:\test_project` 真实贪吃蛇会话（167 事件、4836 model_delta）上做。

## 4. 跟踪（未做，honest）

完成 turn React.memo + 真虚拟化（窗口化已防崩，属性能优化）、seq 游标无缝重连（I2 已保证 correctness）、编辑重发+拖排序、主线内联 diff accept/reject（I11）、session 备份/分支/软删还原（I10）、手动主题开关、逐组件字重/间距字面量收敛。均记于路线文档，非缺陷。

遵守 [[keep-docs-aligned-no-drift]]、[[convergence-direction]]、[[studio-product-convergence-refactor]]、[[truly-complete-system-goal]]。
