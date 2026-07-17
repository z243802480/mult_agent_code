# Agent Project Guidance

## 1. Project Purpose

This project is an agent-ready workspace. Agents must use this file as high-priority project context before planning, editing, reviewing, or reporting.

Project purpose:

```text
Build a local-first harness for general long-task agents: turn compact goals into verified
artifacts through goal specification, on-demand planning, controlled tool/MCP/skill use,
validation, repair, context compression, cost control, and final reporting—with a friendly
CLI and Studio surface (not command-only UX).
```

## 2. Execution Plan (mandatory)

```text
执行计划唯一入口：docs/zh/研发总计划.md（当前状态见 §16 / §16.1）
当前 ACTIVE_PHASE：大重塑 Part B（前端拉齐 + 诚实化收敛）（S77 的 P1 主体已闭合，见下）
当前 ACTIVE_SLICE：B10 **两 named 项已闭合 + 真跑找到的流畅化两刀**（用户令"把前端改到流畅使用的状态·必须往成熟方向走"）：B10-a 上下文预算快照(1.2.55) / B10-b 专家进 worker 树(1.2.57) / F1 状态诚实化-新增 waiting 状态(1.2.54) / F2 长运行渐进式披露(1.2.56)。已落地 B4–B9（专家集群可见 / 护栏 hook / 模型 todo / 成本归属 / schema 防漂 / 完成闸判据）。权威定义见 研发总计划 §16 + changelog 1.2.30–1.2.84（本处为镜像·单一真源）。**Wave N2「评论即指令」已收官见 1.2.84**（2026-07-17 用户"push it,然后继续 N2"：G4 diff 行级评论回喂[行 hover 评论→托盘批量提交→运行中 steer/空闲新 turn·失败不清空·真栈验模型逐条精确执行] + G5 AI 自审[改动面板一键·chat 只读 turn 带 diff·结论按 文件:行 锚回 diff 视图·真栈验埋 bug 精确挂行；纠偏:runtime review 无文件锚非纯接线,按主流语义走消息通道]·零新后端协议·vitest 152+smokes 33+Playwright 4 全绿；**Wave N3「计划与回滚」已收官见 1.2.85–1.2.89**（自驱循环四轮：G6刀一计划步骤评论回喂 1.2.85·真栈验三约束全遵守 / G11 证据分组+截断披露+内联预览 1.2.86 / G10 预览控制台=错误条+宽度预设+外开 1.2.88 / G7 rewind 文件回滚=影子快照+diff 预览确认+可反悔 1.2.89·真栈 UI E2E；途中抓修两真 bug：session.json 并发写竞态=会话静默消失 1.2.87、事件合并 localeCompare 时区错序 1.2.89；后续=G6刀二/G8 待 DecisionPoint；P2 已开动:G15 会话回放导出=自包含 HTML 回放页已落 1.2.90,G14 记忆标签只读起步已落 1.2.91,G17 图片粘贴=**原「通道未就绪」搁置记录已于 1.2.95 撤回**[1.2.91 的架构断言经活体探针证伪:content 是裸标注·零改动传 parts 数组即通·glm-4v-flash 真读出图中数字;真缺口只剩视觉路由档(实配 coding 端点拒图 400/1210)+前端;后端仅 ≈30 行·openai_compatible 一行不用改=与另一会话零冲突;教训:纯读代码的「不可能」必须标未验证],真 friction 修复:首次点击会话线程空态=重选当前会话误清转录已修 1.2.92,测试端口五组撞车消重+唯一性守卫已修 1.2.93,回归自审 3/8 角度+首批处置 2 修 8 记录见 1.2.94[五角度撞额度上限未跑成·待补],自驱循环推进中）。**Wave N1「安静可信赖」已收官见 1.2.83**（G20 语法高亮/G2 常驻上下文环/G1 OS 通知+favicon 状态点/G9 队列编辑重排/G3 会话状态徽章+归档+过滤+7s 轻轮询·五刀一刀一验一提交）。轮内叙事顺序回正见 1.2.82（用户"不知道模型在回答我什么·心流不顺"→1.2.64 answer-first 的对标声称是错的·主流=过程在前答案收尾·已交换渲染序+测试钉死；顺带修 smoke 端口轮盘撞活 BFF + 14 会话软删事故全量恢复[调用方无法归因·软删设计救了数据]）。第二轮目视四刀见 1.2.81（用户截图指名：宽屏居中 768 阅读列 / 跳到最新改圆形浮钮+修 smooth 后台失效 / header=标题乱码第三泄漏点+守卫 total 化 / Preview 按会话触碰文件作用域化不再跨会话泄漏）。主体内容渲染三硬伤已修见 1.2.80（用户目视抓到 1.2.79 审计盲区：答案截肢[splitLeadAndDetails 白名单化]/假 Markdown 解析器[换 react-markdown+remark-gfm]/量表倒挂[h3 11px<正文·重建 em 量表 15px/1.7]·真会话复测+11 测试·116 vitest+33 smokes+4 Playwright 全绿）。**前端对标现行真源（2026-07-16 全面审计·1.2.79）= `docs/zh/前端对标主流差距与实施路线.md`**（15 项主流收敛范式×19 项差距 G1–G19 分档+实施思路；接替已删除的《前端产品化路线》；Wave N1「安静可信赖」=通知/常驻 usage/会话状态徽章+归档/队列编辑，待用户点火）。同批删除 22 份已完成执行文档（21 brief+旧路线·登记 §2c·保留 S54）。#5 视觉密度=客观对比度收边见 1.2.69（截图工具坏→用 javascript_tool 读真实计算样式跑 WCAG 审计·抓成功绿 `--ok` 小字文字对比度 3.1~3.5 失败·拆文字专用 `--ok-text`+`--ok-border`·两主题真浏览器验 3→0 失败·视觉手感部分诚实交用户目视）。侧栏 session 名乱码见 1.2.68（诊断纠偏:大多是终端显示假象·真损坏 5 个是 bash/curl 测试污染非产品 bug·Node fetch 实验证浏览器路径 UTF-8 无损;真弱点=显示守卫漏→`cleanSessionTitle` 改按幸存内容判(杂多国字母=debris)+`sessionPreview` 同守卫堵第二处泄漏·真浏览器验 5 损坏→未命名会话零误伤）。主对话区资深用户视角审视打磨见 1.2.58（真跑 live run + 代理测绘·修 5 刀英文泄漏/哑信号/徽章按轮/启动计时·滚动跟随因无法干净验证已 revert 并开后台任务）。投运心流复核后修信任噪音三小修见 1.2.59（「已中断」假阳性=settled 信号真跑闭环验证 / mojibake 标题=剥 lone surrogate 救回中文 / 英文枚举泄漏=Status·tier·调度模式本地化）。投运交付=生产构建单入口见 1.2.60（发现 server.mjs 单口托管+asteria studio 单口判定早已就位·真缺口是从没人构建 dist→补 `asteria studio --build` + 重写 start-studio.ps1 为生产单入口·两入口真跑端到端验证 8787 单口）。LICENSE 接线加固见 1.2.61（审计「无 LICENSE」P0 已过期·根 LICENSE 早存在且到位·加固周边接线=pyproject `Private :: Do Not Upload` 硬闸 + studio package.json license + README 披露·**至此投运 P0 只剩真沙箱**）。发包就绪复核（真跑 build_beta_release 出完整包 wheel+studio+beta+checksums·ok:true）+发布绿灯门见 1.2.62（release 打 tag 直接 build+upload 不跑测试门→verify.yml 加 workflow_call 变可复用 gate·release `needs: verify`·代码红永不发资产·加门前证 main pytest 1290 passed 可绿；顺修 build_beta_release --dist-dir 透传 bug f7a9e45）。beta_safe 红队跑一轮见 1.2.63（现有套件 120 全绿+活体新向量探针·beta_safe 密不透风+网络外泄 13 新向量 0 泄漏·挖到 3 auto-mode gap 修 2 干净的:git clean force / `.git/` 重定向不一致·`>`截断有双用取舍未修·全量 pytest 1297 passed）。**前端对标 Claude Code 拆解 + #1 叙述去重见 1.2.64**（用户体感"差距很大"四轴全中=功能齐但交互质感低一档·真跑拆成 5 项 backlog:#1 叙述冗余[已修·answerLed 丢 narration+验证→✓徽章]/#2 diff 内联[已修 1.2.65·InlineFileDiff 懒加载 gitDiff+复用 DiffPreview·保留聚合 chip·顺修 not-a-git-repo 英文泄漏]/#3 即时感[已修 1.2.66·先划物理天花板(subprocess 冷启动不了)·真压 BFF tail 节奏:首看 1200→300ms+轮询 1200→500ms+fs.stat 大小守卫让快轮 stat-only 不重读→首事件 ~2.4s→313ms·LiveStream 补 elapsed 计时(锚最早 created_at·remount 不回零)]/#4 工具输出内联[已修 1.2.67·纯前端 bug 非缺数据:shell stdout 早在 `tool_result` 事件 `data.stdout`(RunCommandTool 写·`_tool_result_data` 只剥 content/diff 保留 stdout/stderr)·ToolCallCard 只读了空的 content_delta→抽 `toolResultOutput` 回落 data.stdout+去掉 Focus 的 `!compactDiff` 禁用·折叠 disclosure 零密度代价]/#5 视觉密度[截图坏需目视]·#5 客观对比度已收 1.2.69）。**补短板双线开工见 1.2.70**（backlog 收完复盘·纠正陈旧记忆:pause/排队/side-ask 早已在·server.mjs 已 1892 行进 CI→地基不再是短板;真剩两条并行——**A** runtime 活起来出 ADR-0029 提案[turn 边界注入点已天然存在于 `turn_start` hook·机制①steer 照抄 pause 触认知环待授权·机制②warm worker 环外审定即落·代码未落地] / **B** 视觉确定性债诚实收敛[暗色 muted=0 漏网诚实纠偏·补 `--danger` token 定义收隐藏债(#c0392b 选值过 AA·composer 零变化)·`#fff`→`--accent-fg`·surface/border fallback 与 183 处间距 codemod 留用户决策]·**诚实结论:真差距主体=主观手感(需用户目视)+runtime 冷批处理(A 线架构活)**）
当前 Brief / 审计签字：docs/zh/reports/S77-commercial-readiness-audit-20260704.md（实现≈71%、市场化 37→利基 43-45）。⚠️ **该报告的 P1④「自主环未闭合」/ P1⑥「DebugAgent 占位」已过期**——三环+软保险丝第四环已闭合且随权限档默认开（changelog 1.2.31/1.2.33/1.2.38），`agents/debug_agent.py` 已删（RA7b）。读该报告须对照 changelog。
执行顺序：Part B 前端拉齐剩余（上下文预算快照 / 专家进 worker 树）→ P0 沙箱（唯一剩余 P0·按内部发动机定位已降级）→ 利基 Beta
冻结（仍有效）：新编排 Wave、任务批 disjoint-write 调度（task_graph 冻结点·需重建冲突检测）、无真实 friction 证据的 Studio 新功能、北极星/swarm/12-Agent、真 cloud VM background。
**已解冻并落地（勿再当冻结项）**：①B1-a/B1-b 并发专家（含隔离并发写）**全局默认开**·随权限档·merge-gate 保护（2026-07-14·ADR-0023·v1.2.33）；②**自主环四环**（auto_repair / auto_replan / auto_replan_goal / auto_continue 软保险丝）**默认随权限档开**（auto/reviewed_auto → ON·ask_everything → OFF·2026-07-13/14·ADR-0017/0027·v1.2.31/1.2.38）；③**auto-accept 默认开**——`run` 不再为 promotion 停下等人审（2026-07-13 用户知情同意·推翻 2026-07-02 的「run 必停」DecisionPoint·v1.2.15）。高危 shell/deploy/push 仍走常开硬 guard。
```

Any agent must read `docs/zh/研发总计划.md` before code or doc changes. Do not start a new
orchestration wave, enable global parallel writes, or add maintainer commands unless the master
plan todo explicitly allows it.

Reference-first: before each Vibe Slice, read `benchmarks/reference_briefs/Sn.md` (create if missing).
No brief → no coding. Learn from OpenCode / Claude Code / Codex-rs mechanisms; do not reinvent wheels.

## 3. Code Triage Lock (Phase 0–2)

**锁的口径已从「文件名」改为「能力」**（研发总计划 §6 是权威；**禁止用文件名或历史代码量保护重复责任**）。大重塑（ADR-0022）的用户授权**显式覆盖本表**：FSM 认知脚手架已按授权整体删除，`execute_command.py` / `run_command.py` / `gate_status_command.py` 已在授权范围内大改。**下面这张表是能力口径的镜像,不是文件白名单。**

| Tier | Rule |
| --- | --- |
| **KEEP_CORE** | 别删这些**能力**: run/execute/plan/chat/status/review/accept, 立真身脊梁(`model_driven_turn`), user_progress_logger, runtime_progress, candidate/merge/promotion, studio server/Thread/Composer, schemas, core tests。⚠️ 原文写的 `agent_loop_*` **已按 ADR-0022 授权全删**(FSM 认知脚手架)——保护的是"执行循环这个能力"，不是那些文件名 |
| **KEEP_PLACEHOLDER** | 别扩展: sandbox rollout(OS 级沙箱仍是 P0 未做), 已弃用的 Agent 类, legacy event_logger fallback。⚠️ 原文的 `disjoint_write real parallel` **已解冻并默认开**(ADR-0023)，不再是 placeholder |
| **HIDE_NOT_DELETE** | 对用户隐藏、CI 保留: daily/weekly/roadmap, gate/acceptance/validation/real-model-*, evidence-bundle |
| **MERGE_OR_TRIM** | Phase 1b only: delete runs_command.py; merge validation→validation-run; trim CLI aliases; remove Studio fake completion |
| **DO_NOT_TOUCH** | 默认不重构: `execute_command.py`, `run_command.py`, `gate_status_command.py`, acceptance/real_model stack。**例外(已授权)**: ①追加 user_progress 字段/卡片一律允许；②大重塑 Part A/B 的脊梁与自主环改动（2026-07-04 解冻、2026-07-05 gate_status 解锁）。**授权之外仍禁止顺手重构**——不夹带无关格式化/重排 |

Full table: `docs/zh/研发总计划.md` §6。**本表与 §6 冲突时以 §6 为准。**

## 4. Non-Goals

Agents must not silently expand the project beyond these boundaries:

```text
Do not build an unrestricted agent chatroom.
Do not allow destructive shell actions without policy approval.
Do not depend on a single model provider.
Do not skip schema validation for persisted runtime objects.
Do not prioritize a gate dashboard before harness + user_progress work.
Do not copy proprietary implementations from reference products.
```

## 5. Current Assumptions

```text
MVP proof: coding harness first (Goal→Plan→Execute→Verify→resume); doc/creative tasks reuse the same loop.
Autonomy: 随权限档绑定。auto / reviewed_auto → 自主环 + auto-accept 默认 ON（失败自修/重规划/续跑，
  promotion 自动 finalize，不再停下等人审）；ask_everything → 全部 OFF。
  ⚠️ 本行原文写「promotion … must interrupt」——那是 2026-07-02 的 DecisionPoint，已于 2026-07-13
  经用户知情同意推翻（set-and-forget 产能观）。**仍然必须打断人的只剩**：高危 shell / deploy / push
  / 不可逆外部副作用（常开硬 guard，不随权限档放松）+ 预算 hard-stop。
Backend first + Studio in parallel on user_progress / runtime_progress contract.
MVP endpoint: studio-benchmark task small_code_change score >= 0.8 with real provider (Slice S7).
North Star and swarm parallel write: only after S7 gate (Phase 3+).
MVP uses filesystem + JSON/JSONL before SQLite.
User-facing CLI: goal, plan, ask/chat (run remains compatibility alias).
```

## 6. Architecture Notes

```text
Runtime layers: CLI, command router, harness (Run/Execute/AgentLoop), context layer, agent layer,
tool layer, evaluation layer, persistence layer.
Root runtime state lives in .asteria/.
Primary user workflow: init -> goal -> status -> resume/decide -> review -> accept.
Maintainer/CI: gate, validation-run, acceptance, evidence-bundle (hidden from default help).
```

## 7. Commands

Use these commands when available:

```yaml
install: None
run: None
test: pytest
lint: ruff check .
typecheck: mypy src
build: None
format: ruff format .
```

Phase 0 verification:

```yaml
doc_contracts: pytest tests/unit/test_documentation_contracts.py -q
```

If a command is unknown, do not invent it. Detect it from project files or create a DecisionPoint when the choice matters.

## 8. Coding Conventions

- Follow existing project style before introducing new style.
- Prefer small, verifiable Vibe Slices (see benchmarks/vibe_slices.json).
- Add tests when behavior changes.
- Avoid unrelated refactors and DO_NOT_TOUCH files.
- Keep generated code readable and maintainable.

## 9. UI and Experience Conventions

- Studio is a first-class client of runtime evidence (not a second runtime).
- Default UX: Goal / Plan / Ask + session narrative; Inspector for raw evidence.
- Do not expose maintainer gate vocabulary on the main thread.

## 10. Safety Boundaries

Protected paths:

```text
.env
.env.*
secrets/
.git/
*.pem
*.key
id_rsa
id_ed25519
```

Agents must not:

- Read secrets without explicit approval.
- Run destructive shell commands.
- Install global packages.
- Push secrets, credentials, protected files, local route/key files, `.env*`, private keys, or other sensitive local data to remote repositories.
- Push code or documentation only when the user explicitly asks for it, after checking the staged diff does not include protected paths or real secrets.
- Deploy to production.
- Send sensitive local data to network services.

## 11. Decision Policy

Default decision granularity:

```text
balanced
```

Create a DecisionPoint for major product direction, stack tradeoffs, privacy/security/network, scope expansion, high cost, irreversible changes, and budget hard-stop (0.90).

## 12. Cost Policy

Default budgets:

```yaml
max_model_calls_per_goal: 200
max_tool_calls_per_goal: 1000
max_iterations_per_goal: 32
max_repair_attempts_per_task: 4
max_replans_per_task: 2
context_compaction_threshold: 0.75
hard_stop_threshold: 0.90
```

See full policy in prior AGENTS sections; long-task autonomy is governed by goal progress, context pressure, repair/replan limits, permission risk, provider health, and loop detection.

## 13. Agent Operating Rules

All agents must:

- Read AGENTS.md + 研发总计划 + ACTIVE_SLICE before acting.
- Produce durable artifacts, not only chat text.
- Respect triage lock and reference briefs.
- Verify changes before reporting success (pytest/smoke for the slice).
- Update ACTIVE_SLICE handoff when pausing.

## 14. Handoff Requirements

Before long pauses, preserve: goal, definition of done, ACTIVE_SLICE, modified files, verification results, failures, open risks, next actions.
