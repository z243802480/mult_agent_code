# S74 文档 × 实现一致性审计

日期：2026-06-29
状态：审计快照（evidence-backed），收敛期参考
方法：按设计资产 §4 拆 6 个域，逐域并行只读审计，每条结论带 `file:line`。
依据：`研发总计划.md`、`S74_SYSTEM_AUDIT_VERDICT.md`、`S74_REFERENCE_PRODUCT_BASELINE.md`、ADR 0005–0015、AGENTS.md §4/§10/§12。

> **2026-06-30 裁决落地（用户逐项拍板）**：§3 行为/默认与 §1 边界项已决并实现——
> **D-1** 已隐藏（north-star flags → maintainer，`b14edd3`）；**D-2** ask/chat 默认权限改只读 `ask`；
> **D-3** 保留 cheap=fake 但混配真 provider 时发运行时告警；**C-6** 确认 base2/profile3 分层并文档化；
> **P0-3** smoke 瞬时救活记 `recovered`；**P0-4** gate reconcile 记 `degraded`。详见 `研发总计划.md` §15 v1.2.6。
> P0-1（user_progress 根 schema 漂移）/P0-2（capability_decision schema）已于 2026-06-29 修复；
> **残留待办**：18 对同名 schema 逐字节一致性测试（P0-1 建议）尚未落地。

---

## 0. 总评

S74 收敛的**大主张在代码里基本成立**，不是纸面：

- `goal_policy` 概念已**彻底删除**（src/ 与 studio/ 零引用，仅留负向断言测试）。
- 默认循环就是单一 `model → tool → observation → model`，**没有第二编排器**；Run 不自动 Review/Debug/Replan（ADR-0014）。`DebugCommand` 已是薄适配器，复用 `ExecuteCommand`。
- `RuntimeReadinessGate` 全局总闸门**已从 src/ 删除**；风险在动作边界执行（PathGuard / permission hard-guards / merge-gate / promotion queue）（ADR-0013）。
- 单一 `BudgetController → context_pressure → compact` 压力路径；hard-stop 仅限轮次/预算/上下文（ADR-0010）。
- 能力按需发现（permission 过滤的 discovery_view），**不再全量目录注入 prompt**（Batch C）。
- 多 provider 路由真实存在（GLM/MiniMax/zhipu/local/openai-compatible 各 tier 独立），非单栈绑定。
- real-model **acceptance** 路径：超时/部分诚实记为失败，复核真实 artifact，**未发现凭空伪造成功**。

因此“不匹配”主要是两类：**(A) 文档滞后于已删/已改的实现**（doc-stale，零代码风险），和 **(B) 少数真实的完整性 / 一致性缺口**。下面按可执行性分级。

---

## 1. P0 — 完整性缺口（最高优先，触及“不跳过 schema 校验 / 不合成成功”非目标）

| # | 发现 | 证据 | 类型 | 建议 |
|---|------|------|------|------|
| P0-1 | **user_progress schema 漂移**：运行时加载的 **根** `schemas/user_progress_event.schema.json` 缺 `transcript_kind`/`ui_intent`/`actions`，整个主线程契约写入时**不被校验**。打包副本 `src/asteria_runtime/schemas/…` 有这些字段。 | 根 schema:1-103（无三字段）vs 包内 schema:74-104（有）；命令经 `parents[3]/schemas` 与 `resources.schema_dir()` 都解析到根副本（如 `run_command.py:169`） | impl-violates（非目标“不跳过 schema 校验”） | 同步两份 schema + 加一条“两目录同名 schema 必须逐字节一致”的测试。**需先 grep 全部生产者确认 `transcript_kind` 取值 ⊆ enum，再跑 pytest 验证收紧不破坏写入。** |
| P0-2 | **`capability_decisions.jsonl` 无 schema、无校验**——它是权限决策的用户侧真源，却以 `schema_name=None` 落盘。 | `capability_decision_recorder.py:95`、`execute_command.py:2142-2145`、`mcp_adapter.py:432`、`skill_adapter.py:333`；两个 schema 目录都无 `capability_decision.schema.json` | impl-violates | 新增 `capability_decision.schema.json` 并把 schema name 传进 append。（`tool_observations.jsonl` 已校验，作对照） |
| P0-3 | **smoke 把非零 `/run` 退出码“判为 transient”后救活成 PASS**。 | `real_model_smoke.py:854-868`，`is_transient_provider_failure` 用 stdout 关键词匹配（timeout/429/500/tls…）`:914-935` | impl-violates（边界）——**已缓解**：救活路径仍跑完整 `validate_artifacts`（真实 artifact + run.json completed + eval pass），不是凭空造假，是“宽松再分类” | 把救活结果记为独立 `degraded/recovered` 而非 plain pass，或加显式 flag。**属 DO_NOT_TOUCH（real_model 栈），需你拍板。** |
| P0-4 | **gate 用 smoke 的 model_calls 把失败的 `model-check` 翻成 passed**，削弱“strong+medium 双路健康”保证。 | `real_model_gate.py:315-349` `reconcile_model_checks_from_smoke` | impl-violates（边界，同样是对真实记录的宽松再分类） | reconciled 的 check 不等同绿色 `model-check` 用于发布签字；或要求探针本身通过。**DO_NOT_TOUCH，需你拍板。** |

> P0-3/P0-4 都**没有凭空造假**——它们复核的是真实 evidence，属“把失败信号宽松降级为成功”。但这正是 S74 裁决明令警惕的“timeout/transient → success”形状，且在 DO_NOT_TOUCH 的 real_model 栈里，**不擅自改，留你决策**。

---

## 2. P1 — Studio 前端一致性（你当前焦点；除特注外均为前端独立修复）

| # | 发现 | 证据 | 状态 |
|---|------|------|------|
| P1-1 | **底部栏前端自撰“评审通过”判词**：`canAccept`→“Review passed…”、`canReview`→“Task complete…”，由能力 flag 推出一个前端并不真正持有的**裁决**（§9 / ADR-0006 “规则冒充完成”家族）。 | `decisionGuidance.ts:88-89` | ✅ **本次已修**：改为中性可执行文案“Changes are ready — review them, then accept to finalize.”/“Ready for review…”，live 验证通过、0 console error |
| P1-2 | `runtimeSessionEvents` 回退**有可能整体替换**真实 transcript：当所选 run 在 session 事件流里无匹配事件时，主线程改用 `runDetail.user_progress` 重建并合成一个 “Goal” 节点。 | `Thread.tsx:62`、`runtimeNarrative.ts:62-120` | ⚠️ **复核后降级**：它读的是真实 `user_progress`（含 `transcript_kind`、`display_level=main` 过滤），**不是** runtime_progress/summary 投影 → ADR-0012 上**站得住**，属“跨流/历史 run 的合法回退”。仍建议：把回退限定到“run 确无 transcript 事件”分支，并对重建结果跑同一 banned-wording 过滤（`runtimeNarrative.ts:73-97` 现无 copy-leak 守卫）。需先确认是否有真实 run 依赖该回退。 |
| P1-3 | **两个下一步面（inline SuggestedActions vs 底部 RuntimeSnapshot）各自推导**，靠 `suppressSuggested` 互斥打补丁而非单一真源；底部栏固定在会话底，非“跟在结果之后”。 | `ConversationTurn.tsx:262`、`Thread.tsx:71,125`、`Studio 会话与上下文设计准则.md:216` | 待办（前端）：以 `event.actions` 为唯一下一步源，底部 affordance 内联到末轮 final 之后 |
| P1-4 | `narrativeKind` 仍以 `phase==="plan"/"review"/"execute"` 回退推导 plan/verify（已删的 WorkflowPhaseStrip 余味）；仅在缺 `transcript_kind` 时触发。 | `narrative.ts:72-75` | 待办（前端，低）：去掉 phase 回退分支，未知→thinking/turn |
| P1-5 | 全英界面里混入中文系统串：`运行详情`（折叠 final 的 summary 标签）、`暂无证据`、错误边界“Studio 渲染失败/刷新 Studio”。 | `TurnFinal.tsx:29`、`Shared.tsx:47`、`main.tsx:27-30` | 待办（前端，低）：归一为英文 |
| P1-6 | 重复 `firstText` 帮手，签名不同（`unknown[]` vs `string[]`），潜在分叉。 | `narrative.ts:217` vs `threadUtils.ts:11` | 待办（前端，低）：合并 |

> 边界检查**通过**（无需动）：Inspector 与主线程边界清晰（WorkflowMonitor/VerificationMatrix/EvidenceExplorer/gate SignalCard 全在 inspector/sidebar，未进 Thread）；`TurnFinal` 的对话优先复盘（lead 文 + 默认折叠结构尾）符合 CV-B/CV-C，无客户端打字机、无伪造 “Done.”。

---

## 3. P1 — 行为 / 默认值（需你决策，非纯一致性）

| # | 发现 | 证据 | 为何需决策 |
|---|------|------|-----------|
| D-1 | 主命令 `run/goal` 暴露 `--toward-north-star` / `--max-slices`，把**冻结的 North Star 多 slice 监督循环**挂到默认用户命令上。 | `cli.py:716,721` → `SupervisedGoalLoopCommand` | North Star 限 Phase 3+ 且在冻结表（AGENTS.md §2）；要不要隐藏到 maintainer 入口 = 产品决策 |
| D-2 | `chat`/`ask` 默认 `--permission-level balanced`（→ reviewed_auto，auto_allow_low_risk），但文档把 Ask 定义为**只读/不改文件**。 | `cli.py:269` vs `用户交互模型.md:108-114`；对照 `plan` 正确默认 `ask` | 改默认会改 Ask 的实际权限行为 |
| D-3 | 默认路由 `cheap` tier 指向 **`fake` provider**；任何走 cheap 的用途（摘要/分类/部分 model-check）真实运行时可能**静默产出 canned 输出**。 | `default_routes.py:34-41` | 文档 §6.1 示例确实写了 `AGENT_MODEL_CHEAP_PROVIDER="fake"`，是“有意默认”，但对真实跑有静默风险；改默认=路由决策 |

---

## 4. P2 — 文档真源归一（doc-stale，零代码风险；属当前 S74 首序任务“文档真源归一”）

| # | 文档说 | 实现是 | 修哪 |
|---|--------|--------|------|
| C-1 | `运行命令.md` 把 ~9 个兼容别名当现役（`runs`/`history`/`verify-status`/`candidates`/`packaging`/`acceptance-trend`/`release-gate`/`prd-update`/`long-run-*`）。 | dispatch 无任一分支，跑了直接报错。 | 删 `运行命令.md` 里不存在的别名条目 |
| C-2 | `大模型循环与动态上下文设计.md:64-66,83,165-166,230-231` 仍画 **auto Gate→Repair/Replan**、活的 `DebugAgent`、`RuntimeReadinessGate` 为默认循环节点。 | ADR-0013/0014 已删自动门与独立 DebugAgent；Debug/Replan 是显式动作。 | 标注 Review/Gate/Debug/Replan 为显式/maintainer，去掉自动 `Gate→Repair` 边 |
| C-3 | `质量与评估.md` §2 列 8 层 eval、§3/§5/§6 约 25 项指标。 | EvalReport 实现 5 层、确定性计算约 4 项（其余 model-optional、未校验）；Workspace/Permission 在动作边界执行而非 EvalReport 子对象。 | §2 注明 Workspace/Permission 走动作边界；指标列裁到确定性核心或标注 aspirational |
| C-4 | `route`/`route-worker`/`studio-benchmark`、`background`、`studio`/`workspaces` 命令未进 CLI 参考。 | 均已注册（`cli.py:281/317/1374/729/1397/1426`）。 | `运行命令.md` 补 maintainer/Studio plumbing 小节（已对默认 help 隐藏，无需改码） |
| C-5 | `模型供应商规格.md` 把 DeepSeek/OpenRouter 列为显式 provider。 | factory 无专用别名，走 generic openai-compatible。 | 注明经 generic 适配器，或从显式列表删 |
| C-6 | `max_replans_per_task`：AGENTS.md §12 + `docs/en/COST_SECURITY_RISK.md` 写 **2**；`成本安全与风险.md:66`、`数据模型.md:346` 写 **3**；运行时 active profile 落 **3**。 | base budgets=2，active `autonomous_long_task` 覆盖为 3（`policies.default.json:11` vs `:54`）。 | **澄清而非盲改**：是“base 默认 2 / profile 覆盖 3”的有意分层，还是漂移？定一处真源后归一 |

---

## 5. P2 — 工程卫生

| # | 发现 | 证据 | 类型 |
|---|------|------|------|
| H-1 | 受保护路径有 ~5 处**硬编码副本**各自重派，而非从 `policy["protected_paths"]` 取——硬守卫 `PathGuard` 是单一权威且完整，但副本有漂移风险（ADR-0011 单一真源）。 | `fast_path_policy.py:10-17,337-346`、`evidence_bundle_command.py:27-33`、`context_loader.py:227-229`、`runtime_request.py:118,142`、`task_contract.py:151,198` | impl-violates（弱） |
| H-2 | fast-path 风险升级提示**漏了 `.git/`**（不是绕过——PathGuard 仍硬挡，仅 review-tier 提示不一致）。 | `fast_path_policy.py:337-346` | impl-gap（低） |

---

## 6. 主流对标小结（CC / Codex / OpenCode）

系统在机制层已经**对齐主流**，不是形态抄袭：连续 Session 单循环、动作边界权限/沙箱/审批、按需能力发现、对话优先 + Inspector 查证、多 provider。本审计的“mainstream-gap”只有零星几处（如 `grep` 工具对模型只暴露 literal 而非 regex，`agent_tool_surface.py:95-100`——若后端实为 regex 则是契约低估，需核实）。换言之，进一步“更像 CC”的收益**在于把上面 doc-stale 清干净、把 P0 完整性补齐**，而不是加新旁路。

---

## 7. 建议执行顺序（守冻结 / DO_NOT_TOUCH / DecisionPoint）

1. **已做**：P1-1 前端判词去裁决化（本次 commit）。
2. **可立即安全做**（前端独立 + 文档真源归一，属 S74 首序任务）：P1-3/4/5/6 前端清理；C-1/C-2/C-3/C-4/C-5 文档归一。
3. **需一轮 pytest 验证再做**：P0-1 schema 同步（先 grep 生产者取值）、P0-2 capability_decision schema。
4. **需你拍板（行为/默认 或 DO_NOT_TOUCH）**：D-1 North Star flag 可见性、D-2 Ask 默认权限、D-3 cheap=fake 路由、P0-3/P0-4 real_model 宽松再分类、C-6 max_replans 真源。
5. **工程卫生（择机）**：H-1 受保护路径单源化、H-2 `.git/` 提示。

> 禁止：新编排 Wave、全局 parallel_writes、新 maintainer 命令、无 friction 证据的 Studio 新功能（AGENTS.md §2 冻结）。
