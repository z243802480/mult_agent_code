# S74 P1 信任修复落地（2026-07-02）

> 承接 `S74-full-system-claims-audit-20260702.md` §3 的 P1（裂缝②权限承诺是标签 + ③前端诚实化未收口）。
> 核心原则：**绝不发出「声称某能力运行过而实际没有」的 outcome / 标签 / 证据**。该删的删、该接的接、
> 无法真做的**降级为诚实文案**而不假装实现。修复前先派 9 代理验证每条发现的当前 file:line + 最小修复
> （[verify run]，均确认 present、high 置信、无一碰 DO_NOT_TOUCH 文件）。

## 修了什么（7 项，均 additive / 非 DO_NOT_TOUCH）

### P1-A 假 `execution_approval_applied` + 死选项 `approve_similar_for_session`（backend）
- `runtime_policy.py` 的 execution-policy DecisionPoint 渲染了 `approve_similar_for_session`（“Approve similar
  for this session”），但**零消费者**：`has_execution_approval` 只认 `approve_once`，选了它任务仍 blocked，
  却因 `resume_command._apply_execution_approval` 对非-approve_once 返回 `True` 而记下 `execution_approval_applied` 假证据。
- 修复：删除该选项；`_apply_execution_approval` 非-approve_once 改 `return False`（落到诚实的 `constraint_recorded`）；
  `permission_policy.py` 移除对外广告的死标签 `allow_similar_for_session`；`decisionGuidance.ts` 去掉指向该选项的死分支。
- 证据：`resume_command.py:396-414`、`runtime_policy.py:242-260`、`permission_policy.py:52/73`。测试 `test_tool_execution_gateway.py` 同步。

### P1-B MCP/Skill 的 `ask` 是 no-op（backend，**采文档降级**）
- `_mcp_permission`/`_skill_permission` 对 ask_everything/高风险返回 `"ask"`（`requires_decision=True`），但
  McpAdapter/SkillAdapter 只拦 `deny`，`requires_decision` 全仓库无消费者 → **ask 实际等于 allow**，还在
  user_progress 记一条像是「已征询」的事件。且能力契约（`allowed_mcp`/`allowed_skills`）默认空即放行。
- 裁决：真交互式门（复用 execution-approval DecisionPoint + resume）是**新机制**，撞冻结；行为上「本来就跑」，
  故取**诚实降级**：`_mcp_permission`/`_skill_permission` 一律返回 `"allow"`（契约把关、风险仍记在 decision.risk），
  不再假装 ask。文档 `运行命令.md` 同步降级：写入/shell 才走交互式审批；MCP/Skill 由契约把关、不逐次询问，
  **真交互式 MCP/Skill 门列为后续项**。测试 `test_capability_invocation_policy/_mcp_adapter/_capability_decision_recorder` 同步。

### P1-C chat 兜底把 canned 当模型答案（frontend `studio/server.mjs`）
- **C1** 删 `buildChatAnswer` 里的 `looksLikeTask` 关键词短路（>15 字且含 实现/修复/… 就返回静态模板 `chatTaskSuggestion`，
  从不调模型）——后端 `routeUserIntent` 已定 chat/run/plan，此处不得再猜；直落 `chatGeneralAnswer`（真模型路径）。
  连带删除孤儿 `chatTaskSuggestion`。
- **C2/C3** `appendModelNotice` 原是 no-op（`void` 掉参数直接返回），使 `localGeneralAnswer`/`localOutcomePlanAnswer`
  这类**本地模板**被当模型答案零披露。改为：`usedModel===false` 时追加一行诚实提示（“no model was reachable …
  built-in template answer, not a generated one”），措辞规避兜底 smoke 禁词（route/intent/Temporary local fallback）；
  流式兜底路径 `appendChatFallbackDelta` 也过同一披露，避免流式分支漏披露。

### P1-D 标签/文案诚实化
- **D1** Inspector「AI Debug Agent」名不副实（`debugAnswerFor` 是纯客户端关键词模板、无模型/网络）→ 改「Run Diagnostics」，
  副标注明「deterministic read of the selected run, not a model」；按钮 title 同改（仅可见字符串，保留符号/CSS/文件名）。
- **D2** `TurnFinal` 对**无内容的非 error final** 兜底显示硬编码「Done.」（伪造成功）→ 改为不伪造：有内容显真内容，
  无内容显中性「(no final message)」，绝不显成功词。
- **D3**（backend）plan run 开场事件走 `channel="conclusion"` phase="understand"，被 `_transcript_kind` 无条件映射成
  `final`，导致 `latest_main_final_event` 把**开场步**当结论。修：`conclusion→final` 收窄到 `phase=="result"`，否则 `progress`
  （显式 `transcript_kind` 的 conclusion()/final_report_event 不受影响）。`user_progress_logger.py:286`。
- **D4**（backend）`_warn_if_tier_silently_offline` 只从 per-tier `routes` 判断「有真 provider」，漏了真 provider 在
  **全局默认路由**（`AGENT_MODEL_PROVIDER=minimax` + 仅 `cheap=fake`）的情形 → 混配仍静默返 canned。修：把 `default_route`
  折入判据（`real_tiers or default_is_real`），补 2 条回归测试（真默认路由触发告警 / 全离线仍静默）。`factory.py:22-66`。

## 验证
- **backend**：`pytest tests/unit` **894 passed**（含新增 B/D4 回归 + 更新的 A/B 测试）；`ruff check src tests` clean。
- **frontend**：`tsc --noEmit` clean；`vite build` ok（1772 modules）；studio smoke **5/5 通过**
  （chat-fallback / plan-output / chat-lifecycle / chat-stream-final / intent-routing）——证明披露措辞不触兜底禁词、
  删 looksLikeTask 不破路由。
- 均未触碰 execute_command / run_command / gate_status_command / acceptance·real_model 栈。

## 残留 / 明确不在 P1 范围
- **真交互式 MCP/Skill 审批门**（像主流 coding agent 那样逐次暂停征询）是 P1-B 主动降级留下的后续项：
  需复用 execution-approval DecisionPoint + resume 消费 `requires_decision`，属新机制，待放量决策与冻结解除后评估。
- C 的 `streaming_mode="local_fallback"` 结构化信号目前前端仍未消费（只做了文本级披露）；若要 UI 徽章化是更完整版，
  非本批必需。
- approve_once 在任务已非 blocked 时仍记 `execution_approval_applied`（幂等，用户确实批了）——按最小改动保留。
