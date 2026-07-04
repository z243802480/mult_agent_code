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

## Tier B 进展（逐项亲验中，2026-07-04）

- ✅ **B5（部分）focus trap + combobox a11y**：CommandPalette 原有 focus 恢复但**无 Tab trap**（aria-modal 却能 Tab 逃逸背景）+ 无 listbox 语义。已加 Tab trap + 标准 combobox/listbox（role/aria-activedescendant/aria-selected）。studio tsc 净。**未提交**。B5 剩余：长任务进度的 aria-live region、DiffPreview 的 `div[role=button]`→`button`。
- ⏭️ **B7 EmptyState 自适应 = 真缺口但判定不做**：`EMPTY_PROMPTS` 确是硬编码 4 条，但成熟产品（Claude Code/Cursor）同样用通用示例；改自适应需穿入 workspace 语言检测、收益微薄。**诚实地不为凑数而改**（error-recovery / loading 文案多样性另论）。
- 🔎 **B1 error navigation 确认真缺口（中等）**：Thread 有 I7 窗口化 + Jump-to-latest，但**无失败 turn 标记/迷你地图/跳错误**；CommandPalette **不含**"跳错误/跳决策"命令（审计称 I13 有，实为误报——palette 只接外部传入 session+action 命令）。最高产品价值的 Tier B 项。
- ⏳ **B2（diff per-hunk+inline）/ B3（dev-server 预览）/ B4（composer 打磨）/ B6（vitest 组件测试）**：待亲验后实施。
每项：understand（亲验真实状态，不轻信审计二手结论）→ implement（Edit 精确改）→ verify（pytest/tsc/ruff/mypy 相应门）→ 回写文档。撞 Tier C 即停下最小征询。

## 审计溯源（子代理原文，可回溯）

- 前端对标缺口 / 后端自主环+Agent / 后端 gate+生态+加固 三份，2026-07-04。
- 校正代理臆测：MCP/Skill 适配器均**真执行**（非桩）；mypy line211 **仍报错**（代理误称已修）；零默认 MCP/skill 为 policy-driven（补样板即可，非缺陷）。
