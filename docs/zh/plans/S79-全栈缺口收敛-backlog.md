# S79 · 全栈缺口收敛 Backlog（前后端同权重 · 对标成熟商业产品 · 逐项实施）

> 来源：2026-07-04 用户指令——"把已查出的问题排优先级，随后逐个先都完善了先；不止后端，前端也一样，都要基于商业化产品对标，形成符合我们路线的功能/设计/实现"。
> 方法：三个并行只读审计代理（前端 Studio 对标 / 后端自主环+Agent / 后端 gate+生态+加固）综合，关键"要改/被判为假"点已由主 agent 亲验。
> 路线锚点：**团队内部 AI 编程发动机 / 国产化基础设施**（glm·minimax 栈），质量/交互对标 Claude Code·Cursor·Cline·Codex，但不做面向市场的商用竞品。

## 冻结与授权边界（先钉死，避免走偏）

- **用户 2026-07-04 授权前端产品化建设** → 实质解除"无真实 friction 证据不加 Studio 功能"冻结的**前端部分**。据此 Tier B（新交互）可做。
- **仍冻结（用户未提，不擅动）**：北极星 / swarm / 12-Agent、`parallel_writes` 全局默认开启。→ Worker 并行"显性化"只呈现已有 `background_runs` 状态，**不启用/不推广** parallel_writes。
- **仍须 DecisionPoint（战略分叉，不独断）**：Tier C 各项——做到时最小征询，不阻塞 A/B。

## 优先级分层

### Tier A｜立即自主做（显性化已有后端能力 + 诚实化未闭环 + 工程健康；不撞冻结/DecisionPoint）

| # | 项 | 类型 | 现状/改点 | 站点 | 量 | 风险 |
|---|---|---|---|---|---|---|
| A1 | review 打分接 correctness_eval | 后端·诚实化 | `_overall` 用 0.9/0.6/0.2 假分 fallback；改为 run_dir 有 `correctness_eval.json` 时用其真实 `overall.score/status`，无则保留常量（兼容离线模型）+测试 | `agents/review_agent.py:225-237`（穿 run_dir/signal，触及 KEEP_CORE review，走 understand→verify） | 中 | 中（改 review 打分） |
| A2 | 全绿基线：mypy line211 清理 | 工程健康 | `SkillAdapter.from_skill_roots` list 不变型报错；`list[SkillRoot]`→`Sequence[Path\|SkillRoot]` | `commands/execute_command.py:211` / `core/skill_adapter.py:198` | 小 | 低 |
| A3 | 前端：修复轮次**运行态**显性化 | 前端·显性化 | S78 已呈现终止态(exit_reason/Repairs N/M)；补运行中"iteration/repair 进度"(轮次条) | studio Thread/RuntimeSnapshot + server.mjs phase | 中 | 低 |
| A4 | 前端：验证结果聚合可读 | 前端·显性化+诚实化 | VerificationMatrix 数据流是否真断裂**先亲验**；聚合 pass/fail/error 计数 + ✓/✗ 徽章 | studio inspector/VerificationMatrix.tsx / EvidenceExplorer.tsx | 中 | 低 |
| A5 | 前端：Evidence 搜索/过滤 | 前端·体验 | 40+ 证据文件无 filter；加搜索框 | studio inspector/EvidenceExplorer.tsx | 小 | 低 |
| A6 | 后端：gate-status 路由可见度 | 后端·诚实化 | 补 default_route_applied / offline_tier_warnings / all_routes_config | `commands/gate_status_command.py:112-126` | 小 | 低 |
| A7 | 后端：package-check 版本一致性 | 发布卫生 | 读 pyproject.toml 对比 `__version__`，不一致 warn | `commands/package_check_command.py` | 小 | 低 |
| A8 | 前端：per-step telemetry | 前端·显性化 | token/latency/cost 每步 breakdown（成本透明） | studio inspector/SelectedStepPanel.tsx | 中 | 低 |
| A9 | 前端：Worker 状态显性化（**不碰并行开关**） | 前端·显性化 | 呈现已有 background_runs/worker 状态（id/lane/timeout/failure）；**不启用 parallel_writes** | studio WorkflowMonitorPanel/WorkerProgressBar + server.mjs | 中 | 中（守冻结） |

### Tier B｜前端新交互功能（用户已授权前端产品化；排 A 后）

| # | 项 | 现状/改点 | 量 |
|---|---|---|---|
| B1 | Thread 错误标记 + 迷你地图 + 错误跳转 | 长任务(20k+ event)导航差 | 中 |
| B2 | Diff per-hunk 接纳 + inline 注释 | 现仅 per-file Keep/Revert | 中 |
| B3 | PREVIEW-3：dev server 检测 + 代理（SPA/框架预览） | iframe 无法显示 SPA | 中 |
| B4 | Composer 模式/权限/队列交互打磨 | 学习曲线陡 | 小 |
| B5 | 无障碍深化（focus trap + aria-live + semantic） | WCAG AA ~70% | 小 |
| B6 | 组件单测框架（vitest）+ 视觉回归 | 仅端到端 smoke | 中 |
| B7 | 自适应 EmptyState / loading 文案 / error recovery UI | 罐头示例 prompt | 小 |

### Tier C｜战略分叉（须用户拍板方向，做到时最小 DecisionPoint）

| # | 项 | 分叉点 |
|---|---|---|
| C1 | correctness_eval 接 release/validation gate 判据 | 新增 stage vs `validation-run --correctness` flag vs 仅展示（撞 §6 MERGE_OR_TRIM 锁） |
| C2 | 自动 replan 环（第二环） | 涉新任务合成/约束推理边界；与 repair/verify 优先级 |
| C3 | DebugAgent 显式化（代码完整但零生产调用） | 产品上要"显式修复 Agent"还是"让 Coder 带观察重提"？ |
| C4 | S69 对抗验证器（源码不存在，仅旧 .pyc） | 作为独立 slice 重建，还是维持 contract+Review 的 deterministic-first？ |
| C5 | 全局 `max_repair_attempts_total` ledger | 现"有意不接线"（派生 cycle 上限已足）；是否真要全局预算？ |

## 执行顺序（Tier A 内）

A1（诚实化核心）→ A2（硬化全绿基线）→ A3（S78 前端延伸）→ A4 → A5 → A6 → A7 → A8 → A9 → 进入 Tier B。

**进度（2026-07-04，未提交）**：
- ✅ **A1 去假分**：review overall.score 不再用 0.9/0.6/0.2 常量——接 `CorrectnessEvalCommand.score_signal`(只读、不落盘、calls==0 返 None 不误伤非验证任务)，两处假分站点(`review_agent._overall` 模型无分回退 + `review_command._deterministic_tiered_eval_report` fast-path)均改用真实验证通过率；保留模型显式分。+5 测试。全量 **1185 绿**、ruff/mypy 净。
- ✅ **A2 全绿基线**：`from_skill_roots`/`SkillDiscovery` 参数 `list→Sequence[Path|SkillRoot]`(协变)，消除自 S78 起 mypy 唯一残留 line211。`mypy src` 全净。
- ✅ **A3 修复轮次运行态显性化**：主线程 plan-bar 加 `.repairProgressChip`「Auto-repairing · attempt N/M」(运行态、从完整 events 取最新 `auto_repair_attempt`，遇更新的 final 则不显示防陈旧；per-attempt 详情仍留 Inspector 守 compact-thread 约定)。studio `tsc` 净。**验证限制**：需真跑 auto_repair-中途失败 run 才能浏览器实见该态。
- ⏭️ **A4 已满足（亲验推翻审计，无需改动）**：`VerificationMatrix` 组件功能完整(pass/fail/unknown 分类 + 「N pass/M fail/total」tally + ✓/✗/− 图标 + 空态)且已接真实 `runDetail.validation_results`(EvidenceExplorer:485/617)。审计所称"占位/数据流断裂/无徽章"不实。**教训固化**：审计代理的"罐头/占位"判断须逐个亲验，勿据以改能工作的代码。
- ✅ **A5 Evidence 搜索**：EvidenceExplorer 加 `.evidenceSearch` 过滤框——按 `renderLine` 文本过滤各 EvidenceBlock（保留原 index、过滤空块隐藏、标题显 N/M）。studio `tsc` 净。
- ✅ **A6 gate-status 路由可见度**：加**纯信息** `route_table`（strong/medium/cheap 的 provider/model/selection + `offline_tiers` + `silently_offline`），text 输出加「Model routes / Offline tiers」行。**关键**：与驱动 gate readiness 的 `route_environment` 分离——cheap 有意可 fake/offline，绝不因此 block gate。+1 测试，gate 全绿、ruff/mypy 净。
- ⏭️ **A7 已满足（亲验推翻审计，无需改动）**：`package_check_command._version_sync_check`(:196) 已比对 `pyproject.version == __version__` 并报 ok/fail。审计"无版本一致性检查"不实。**第三个"审计误报为缺失、实则已做"的项（A4/A7）**——固化"先亲验"纪律的价值。
- ✅ **A1–A7 已提交**（2026-07-04）：S78 = `ec61caa`，S79 A1–A7 = `52369da`（共享文件 EvidenceExplorer.tsx / 研发总计划.md 随 S79 笔）。未 push。
- ✅ **A8 per-step telemetry**：SelectedStepPanel 加独立 "Telemetry" 段 + `TelemetryView`——把 `event.telemetry` 从原始 JSON blob 变为可扫指标（Latency/Input/Output/Total tokens，探测多别名字段名、无则不显、raw JSON 折叠兜底）。studio `tsc` 净。
- ⏭️ **A9 已满足 + 冻结阻断（亲验推翻审计，无需改动）**：WorkerProgressBar / WorkerTopologyPanel / WorkflowMonitorPanel **都是完整功能组件**（进度轨·worker 树·Metrics·调度徽章），无数据时诚实返回 null。审计"占位/罐头/渲染空白"不实——它们不显示只因**并行/swarm worker 是冻结特性**，多数 run 无 worker 数据。要"更显性化"须有 worker 数据 = 需解冻 parallel_writes/swarm（**明令不碰**）。故无守冻结的诚实改动。

## Tier A 收官（2026-07-04）

**9 项全部处理**：真改动 6 项（A1/A2/A3/A5/A6/A8，全验证）+ 亲验已做/冻结阻断 3 项（A4/A7/A9）。全量 1186 绿、mypy/ruff 净、studio tsc 净。A1–A7 已提交（`ec61caa` + `52369da`）；A8 + 本文档更新未提交。

**关键教训（已固化）**：前端审计代理**大幅over-report"占位/罐头"**——A4/A7/A9 判为缺失实则完整，A3 部分已做。逐个亲验避免了对能工作代码的伪造 churn。**Tier B 各项动手前同样须先亲验**（审计前端结论不可尽信）。

## ADR-0016 第一刀执行（认知归模型/边界归状态，2026-07-05）

用户 2026-07-04 认可"拥抱 AI=给模型合理上下文+工具+目标、模型驱动，不要状态机驱动"。经六大主流产品实证（Claude Code/Cursor/OpenCode/Codex/Cline/Aider，多为 verified-from-source）落 **ADR-0016**（Accepted，强化 0010/0015，不 supersede）：三分类可测判据 §1 认知(禁 FSM)/§2 边界(显式保留)/§3 证据(伪造标量删·证据型 DoD 可把关)+ 合规清单。

第一刀（有界·可回滚，全落地并验证）：
- ✅ **1a `0162008`**：`_handle_auto_repair_round` **no-progress 先判**(0010 §3)，数字 `repair_cap` 退为"仅循环确在进展时才作 resumable 保险丝"——撞次数不再短路 no-progress 信号、伪装成停止原因。always-fail client 现产 `loop_no_progress`(真因)；budget_exhausted 测试改 cap=1。
- ✅ **1b `65df0f5`**：`review._overall` **删 0.9/0.6/0.2 伪造常量** → score=模型自判分/真实验证通过率/否则 **None(未验证)**；`eval_report.schema.json` 双份允许 null；显示"未验证"、reason 标注需人审。用户选 A(未验证不自动过质量闸·须人审)。
- ⏭️ **1c 化妆不做**：`recommended_command_for_next_action` 的 repair→debug 是**给用户/Studio 的提示串、不驱动控制流**(控制流由 `next_action_kind` 直接分支)，溶解它价值低。

关键发现：**acceptance 由 `status` 驱动、非数字 score**，`accept` 本就是独立人工命令(要求 `status==pass`)→"须人审"本就成立；1b 只把误导性假分诚实化、不阻断 docs 任务(保住 A1 顾虑)。全量 1186 passed·mypy·ruff 净。回滚闸：Golden-Task eval 若显示模型驱动 repair 可测更差→关 `auto_repair` 退回。

**合规扫查收口 `e7f1650`**：全库扫 §1 认知漂移，唯一命中 `slice_completion_judge._deterministic_judge` 硬编码 `review_score<0.75`（北极星确定性兜底无视 policy），已改读同一 `min_review_score` policy（默认 None→不虚构门）；其余候选亲验为合法 §2/§3 边界，未误改。认知归模型这条线闭环。

**1b 孪生补漏（fast-path §3 去伪造）**：1b 删了 `ReviewAgent._overall` 的伪造分，但**确定性快路** `ReviewCommand._fast_path_overall` 的孪生分支仍遗留：无可执行验证（doc/creative 快路，`correctness_signal is None`）时返回 `score=0.9` 伪造绿分。已同一 §3 哲学修正：无验证证据→`score=None`（未验证·须人审），`status="pass"` 仍是快路确定性不变量（全 done 无 blocker，生命周期不变）。快路测试只断 status 不断 score，无回归；+2 断言（`test_fast_path_overall_score_is_unverified_without_executable_verification`）。correctness→主 review 接线本已完整：模型收全量 `review_context`（含真实 `correctness_signal`）自判 status（符 §1），模型缺席的 deterministic 分支 status 取 `correctness["status"]`。

## S77 假默认档 · 定向诚实化（2026-07-05，接 ADR-0016 §3 证据线）

S77 §7 把"假默认档 fail-loud"降为定向项（硬 fail 会反转 D-3 决策 + 砸离线测试基础，真实零配置默认其实是 minimax，非假货）。落地的不是硬 fail，而是**让 fake/offline 罐头输出在任何显示面都无法被误认成真实模型**：
- ✅ **机器可读标记**：`RouteDiagnostic` + `ModelRouteResolution` 增 `returns_canned_output` 进 `to_dict()`（doctor/gate-status/status/Studio 路由表都消费）。fake/offline provider → True。
- ✅ **doctor 诚实渲染**：落 fake/offline 的档 `severity="warning"` + 显式「returns CANNED placeholder output (not a real model); set AGENT_MODEL_<TIER>_PROVIDER … for real output」，但 `ok=True` **不翻红**（离线是合法意图，`DoctorResult.ok` 只被 `severity==error` 拉红）。
- ✅ **显示表去中性化**：`default_routes`/`model_failure` 的 fake `base_url`「local offline provider」→「offline canned placeholder (fabricated output — not a real model)」。
- 构造期既有 `_warn_if_tier_silently_offline`（D-3 混用告警）保留不动。
- **验证**：+2 单测（route 诊断标记 / doctor 离线档 warning，`test_model_routing` + `test_control_surface_commands`）；全量 **922 单测绿**·mypy·ruff 净。**注**：`cheap` 不是 doctor check（仅 strong/medium 是），其诚实靠 routes 表标记；doctor warning 分支在 strong/medium 自身落 fake（全离线）时触发。

## S79 · 自主 replan 闭环（第二环，2026-07-05 用户"授权解锁推进"）

承 S78 repair 环，闭合**任务级 replan 环**：模型在任务循环内出 `replan`（"本任务方法根本错了，重新构思"）时，有界预算内自动让 CoderAgent 换方法重试，不再每次就 block 交还人类。brief `benchmarks/reference_briefs/S79-autonomous-replan-loop-closure.md`。
- **关键边界（§2 防 scope 扩张）**：只闭 **task-level** replan（同 goal 同任务边界内重新构思）；**goal-level** `ReplanCommand`（合成新任务 + lineage 计数）= scope 扩张越 DecisionPoint，**保持人类门控不动**。auto-replan 预算耗尽时 `recommended_command="replan"` 荐人类走 goal-level。
- **flag 门控·默认关·可回退**：`agent_loop.auto_replan`（默认 `false`，`agent_loop` 宽松 object 无需改 policy schema）。关时逐字节同今日。
- **落码**：`_auto_replan_enabled`/`_max_replans_per_task` + `_handle_auto_replan_round`/`_block_auto_replan`（镜像 repair 孪生，no-progress guard 先判复用 `_auto_repair_loop_guard_warns`）+ `_execute_task` 分派分支 + `max_rounds` 开时 `+2*replan_cap` + budget 快照补 `replan_attempts_limit`/`auto_replan_enabled`（前端 parity）。
- **有界保险丝**：局部 `replan_attempts_used`（cap=`max_replans_per_task`，默认 2）+ no-progress guard。**不新增 budget replan 计数器 / 不改 cost_report schema**（budget 无 `max_replans_total`，不伪造）。
- **终止**（先触发者胜）：成功→`completed`；局部计数≥cap→`replan_budget_exhausted`(荐 `replan`)；no-progress→`loop_no_progress`；hard-stop 已保。
- **schema-double-trap 踩坑（已修）**：`replan_budget_exhausted` 需同步加**四处**——`schemas/` + `src/.../schemas/` 两份 `agent_loop_run_summary.schema.json` enum，**和** `core/agent_loop_run_summary.py` 的 Python `EXIT_REASONS` 集合（`clean_reason = ... else "no_action"` 会把未登记的 exit_reason 静默降级成 `no_action`——正是首轮 budget-exhausted 测试假失败的根因）+ recovery-chain required 集合。
- **验证**：+4 集成测试（replan-then-succeed / budget-exhausted / no-progress / opt-out 回退）+ 现有 repair/probe 逐字回归；`test_execute_command.py`+run_summary 53 绿·**全量 1193 单测+集成绿·1 skip**·mypy·ruff 净。repair 环（S78）与 replan 环独立预算/exit_reason，一个任务循环内可先后触发。

## Tier B 进展（逐项亲验中，2026-07-04）

- ✅ **B5（部分）focus trap + combobox a11y**：CommandPalette 原有 focus 恢复但**无 Tab trap**（aria-modal 却能 Tab 逃逸背景）+ 无 listbox 语义。已加 Tab trap + 标准 combobox/listbox（role/aria-activedescendant/aria-selected）。studio tsc 净。**已提交 `678a4c5`**。B5 剩余：长任务进度的 aria-live region、DiffPreview 的 `div[role=button]`→`button`。
- ✅ **B4 Composer 打磨 = 大部分已成熟，审计高估**：亲验 Composer 已有 @提及+键盘导航、自动增高、斜杠命令(/ask /plan /goal)、模式/权限分段控件+hint、运行中排队+可删 chip、Esc 停止、side-ask。"学习曲线陡"高估——真实残留仅 aria-live。已给队列加 `role=status aria-live=polite` + 显示队列数。**待提交**。
- ✅ **B5 收尾**：aria-live 残留已补（队列播报 + repair chip 已有 role=status）。审计"DiffPreview `div[role=button]`→`button`"经亲验**误报**——全库 `role="button"` 0 处，DiffPreview 已用真 `<button>`。B5 视为完成。
- ⏭️ **B7 EmptyState 自适应 = 真缺口但判定不做**：`EMPTY_PROMPTS` 确是硬编码 4 条，但成熟产品（Claude Code/Cursor）同样用通用示例；改自适应需穿入 workspace 语言检测、收益微薄。**诚实地不为凑数而改**（error-recovery / loading 文案多样性另论）。
- ✅ **B1 error navigation 已实施**：Thread 有 I7 窗口化 + Jump-to-latest，但**无失败 turn 标记/跳错误**（审计称 CommandPalette 有 I13 跳错误命令，实为误报）。已加：①失败 turn 判定（步骤 `kind==="error"` 或 `status==="failed"`）②ConversationTurn 根节点 `id=thread-turn-N` + `.failed` 左缘 danger 标记 ③sticky "N issues" 导航 pill，点击循环滚动到下一个失败 turn（含窗口化外的 turn 先展开再聚焦）+ issueFlash 高亮。tsc + 完整 vite build 双绿。视觉差异仅在存在失败 turn 时出现（需真实失败会话截图，未 fabricate）。**待提交**。
### Tier B 剩余三项 — 亲验后定性（均非"小/快赢"，各含一处需先拍板的点）

- ⏭️ **B2 diff per-hunk + inline 注释 = 大特性（跨前后端）**：现 `DiffPreview` 仅 per-file `Stage file`/`Discard changes`。按成熟审批模型（文件默认直接改、Accept=finalize），真实价值点是 ①**per-hunk revert**（局部撤销，需后端 `git apply -R` 单 hunk）②**inline 注释→喂给 repair 轮**（与自主环高契合，需注释持久化 + 接 composer/repair）。这不是"中"，是一个独立 slice；且 inline-comment→repair 路径触及自主环编排（Tier C 邻域）。**建议独立 slice，先定 per-hunk-revert vs inline-comment 哪个先做。**
- ✅ **B3 PREVIEW-3 dev-server 反代 已实现**：PREVIEW-1/2 只服务**静态**工作区文件；SPA/框架无法预览。已加 **opt-in 反代**（`--preview-proxy <url|port>` 或 `ASTERIA_PREVIEW_PROXY`）——设置则 preview server 转 HTTP 反代 + **websocket upgrade 代理（Vite/Next HMR）**，未设置保持静态（**不自动探测任意端口**，避免误代理/footgun）。preview-info 报 `mode/target`；前端 PreviewPane 识别 proxy 模式框住 dev-server 根 + "Dev·HMR"chip（跳过 html 文件选择器/空态）。dead dev server 给清晰 502 不 hang。**验证**：新增 `scripts/preview-proxy-smoke.mjs`（起假 dev server 断言 HTTP 反代 + asset 转发 + websocket 101 upgrade + proxy-mode info）✅；static smoke 无回归 ✅；tsc + vite build 双绿 ✅。**待提交**。
- ⚠️ **B6 vitest 组件测试 = 与既有测试范式冲突，属工具链决策**：studio 现有 **~20 个 `node scripts/*.mjs` smoke/unit + playwright** 交互测试，无 vitest/jest/testing-library。按 AGENTS.md §8"先随既有风格"，引入 vitest+testing-library+jsdom 是**新增并行测试范式 + 依赖安装**，非机械补测。宜作 DecisionPoint：引 vitest vs 扩展现有 node-script/playwright 覆盖。**不擅自装工具链。**

> 本轮已交付并提交：B5(`678a4c5`)、B1(`8f5d3c7`)、B4/B5 收尾(`3c51268`)。剩 B2/B3/B6 各需一处先行拍板（B2 slice 拆分 / B3 可直接做为最高价值项 / B6 工具链选型），非"逐个快赢"，故在此 checkpoint 交由用户定下一步投入。
每项：understand（亲验真实状态，不轻信审计二手结论）→ implement（Edit 精确改）→ verify（pytest/tsc/ruff/mypy 相应门）→ 回写文档。撞 Tier C 即停下最小征询。

## 审计溯源（子代理原文，可回溯）

- 前端对标缺口 / 后端自主环+Agent / 后端 gate+生态+加固 三份，2026-07-04。
- 校正代理臆测：MCP/Skill 适配器均**真执行**（非桩）；mypy line211 **仍报错**（代理误称已修）；零默认 MCP/skill 为 policy-driven（补样板即可，非缺陷）。
