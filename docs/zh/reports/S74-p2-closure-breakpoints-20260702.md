# S74 P2 核心闭环断点落地（2026-07-02）

> 承接 `S74-full-system-claims-audit-20260702.md` §3 的 P2（裂缝④ 闭环断点 + 能力不可见）。
> 修复前先派 6 代理各钉一项到**当前代码**（pull 到 `498d31c` + P1 `b921028` 之后），复核是否仍断、
> 最小诚实修法、是否撞 DO_NOT_TOUCH / 冻结。原则同 P1：能真做的接、撞 DO_NOT_TOUCH 的降级为诚实文档
> 而非破锁，真接线须经 DecisionPoint。侦察还纠正了审计两处夸大（见下）。

## 结论表（6 项）

| 项 | 仍断 | DO_NOT_TOUCH | 裁决 | 验证 |
| --- | --- | --- | --- | --- |
| P2-1 skill/MCP 观察回灌 | 是 | 否（gateway） | **实现** | 新增 gateway 跨轮测试 |
| P2-4 4 工具被硬拒 | 是 | 否 | **实现** | 新增 policy 测试 |
| P2-5 route_fallback 只在内存 | 是 | 否 | **实现** | 新增 logger 落盘测试 |
| P2-6 chat 单轮失忆 | 是 | 否 | **实现** | 新增 history 测试 + studio smoke |
| P2-2 /run 掉 review | 是 | **是**（run_command.py） | **文档降级** | doc-contract |
| P2-3 repair 预算死接线 | 部分 | **是**（execute_command.py） | **诚实标注 + DecisionPoint** | doc-contract |

## 4 个代码修复（均非 DO_NOT_TOUCH、非冻结、审计已授权 P2）

### P2-1 skill/MCP 观察不回灌下一轮（`core/tool_execution_gateway.py`）
- 根因：MCP/skill 结果只在**同一 attempt 内存**里回灌；每轮开头 `execute_command._refresh_harness_observations`
  用 `load_harness_observations(disk)` 覆盖，而后者只认 `channel=='execution_chain'` 且带 `data.observation` 的事件。
  gateway 的 mcp/skill 分支 `continue` 早退、从不发该事件，adapter 写的是 `channel='tool'` → 跨轮被冲掉。
  **纠正审计**：不是「任何本地工具同轮冲掉」，而是**跨轮 reload 边界**丢失（本地工具因发了 execution_chain 事件而幸存）。
- 修法：`_run_mcp_call`/`_run_skill_call` 在 `object.__setattr__(harness_observation)` 后补一句与本地工具**完全相同**的
  `_record_harness_observation(...)`（同时写 execution_chain turn 事件供 reload + tool_observations.jsonl）。capability_decision
  传 `{}`（真决策已在 adapter 自己的 mcp/skill_invocations.jsonl 证据里，不伪造）。**不碰 execute_command.py**。
- 测试：`test_tool_gateway_skill_observation_survives_next_round` — 断言 skill 调用发出 execution_chain observation 事件，
  且 `load_harness_observations` 能跨轮 reload 出来。

### P2-4 4 工具被过期 capability-kind 映射硬拒（`core/capability_invocation_policy.py` + `agents/planner.py`）
- 根因：`_TOOL_KINDS` 缺 `find_files/diff_workspace/todo_read/todo_write` → kind `unknown` → `tool_permissions.get('unknown','deny')` 硬拒，
  但 agent tool surface 却广告它们。此外 `find_files/todo_read/todo_write` 不在 planner `_allowed_tools`（第二道契约门也拒）。
- 修法：`_TOOL_KINDS` 补 4 条→`read`；planner `_allowed_tools` 把 `find_files/todo_read`（只读）加进 readonly/report/default，
  `todo_write`（只写 run-local 计划态、非 workspace）加进 report/default。两处均非 DO_NOT_TOUCH。
- 测试：`test_capability_invocation_policy_maps_newer_read_tools_not_denied` — 4 个 tool_kind=='read' 且 decision!='deny'。

### P2-5 route_fallback 只在内存（`models/model_call_logger.py` + 两份 `model_call.schema.json`）
- 根因：`RoutedModelClient.chat` 只把 fallback 打到 transient 的 `request.metadata` / `response.raw_response`；
  per-call 持久化 `_base_record` 拷 `model_route` 却不读 `route_fallback` → strong→medium 降级在真实 run 里无可查证据。
- 修法：`_base_record` 在拷 model_route 后加 `route_fallback = request.metadata.get('route_fallback')`（medium 重试的 metadata 已带），
  落到 `model_calls.jsonl`；两份真源 schema（`schemas/` + `src/asteria_runtime/schemas/`，不动 build/ 与 .asteria/tmp）补可选字段。
- 测试：`test_model_call_logger_persists_route_fallback` — record + jsonl 均带 route_fallback，过 schema。

### P2-6 chat 单轮失忆（`commands/chat_command.py` + `studio/lib/chat-route-context.mjs` + `studio/server.mjs`）
- 根因：`ChatCommand` 纯单轮（messages 硬编码 `[system, user]`）；Studio 每条消息 spawn 新 python 进程、零共享；
  近 3 轮只喂 orchestration 路由、从不进答案生成。轮次其实已落在 `.asteria/studio/sessions/<id>/events.jsonl`，只是没人注入。
- 修法：`ChatCommand.__init__` 加可选 `history`（有界：近 6 条、每条截 800 字、只收 user/assistant），messages 变
  `[system, *history, user]`；CLI 不传（单命令天然单轮，行为不变）。studio 侧新增导出 `recentChatHistoryMessages`
  （复用既有 turn 抽取 + execute 边界，只保留**已完成**轮次、丢当前在飞问题），`chatModelAnswer` 从 events.jsonl 取近 N 轮注入
  base64 payload → `ChatCommand(history=...)`。**复用现有 events.jsonl，不新建持久层、不加 UI**——属既有能力失忆闭环，非冻结的新功能。
- 测试：`test_chat_command_history.py`（角色过滤/有界/裁剪/默认空）+ 更新 chat-stream-final 假桩接受 history kwarg。

## 2 个撞 DO_NOT_TOUCH 的项 → 诚实文档降级（真接线列 DecisionPoint）

### P2-2 /run 不再内联 review（doc-downgrade）
- 自查证实：`run_command.py` **无** `ReviewCommand` 调用、**不写** `eval_report.json`/`review_report.md`，只 `_latest_review_status`
  **读** `eval_report.json`（缺失→`unknown`）；`real_model_smoke.run_smoke` 同样不调 review。matrix 表里的 `run_review` 行是
  review 尚在 `/run` 内联时的**历史**（现留死代码，DO_NOT_TOUCH 不删）。
- 降级：`运行命令.md` 改正「/run 内联跑 review 并生成 eval_report/review_report」为「review 由独立 `asteria review`/accept 产出、
  /run 只读、缺失报 unknown」；`真实模型验收.md` 通过标准第 5 条（eval_report overall==pass）标注「仅当已跑 review 时适用」。
  **注意**：`运行命令.md` §3.7 对 `/review` 命令自身的 deterministic-first 描述准确，未动。
- **DecisionPoint（留给用户）**：若要让 `/run` 真的接回 review 步，须改 `run_command.py`（DO_NOT_TOUCH），需解锁例外。

### P2-3 repair 预算死接线（诚实标注）
- 自查证实：`BudgetController.record_repair_attempt()` 全仓库仅定义、零生产调用者 → `max_repair_attempts_total` 永不触发。
  **纠正审计**：`max_repair_attempts_per_task` 并非全死——`run_command` 据它派生 recovery inner-cycle 上限（粗代理）。
- 标注：`质量与评估.md` 补注 `_total` 未接线、真正生效的是派生 cycle 上限 + no-progress 检测。
- **DecisionPoint（留给用户）**：唯一逻辑正确接线点在 `execute_command.py` 的 repair 派发（DO_NOT_TOUCH），且会改控制流
  （超限 raise），属逻辑改动非「追加 user_progress」→ 真接线须解锁 DO_NOT_TOUCH 例外。

## 验证
- backend：`pytest tests/unit` **900 passed**（含 6 条新增/更新测试）；`ruff check src tests` clean；`test_documentation_contracts` 22 passed。
- frontend：`tsc --noEmit` clean；`vite build` ok（1772 modules）；studio smoke **7/7**
  （chat-fallback / chat-lifecycle / chat-stream-final / friendly-ssl-error / intent-routing / plan-output + 前述）。
- 未触碰 `execute_command.py` / `run_command.py` / `gate_status_command.py` / acceptance·real_model 栈。

## 残留 / 明确不在 P2 范围
- **真接回 /run review**（P2-2）与**真接 repair 预算 gate**（P2-3）均须解锁 DO_NOT_TOUCH → 已列为 DecisionPoint，等用户拍板。
- P2-6 的 `streaming_mode`/历史 UI 徽章化未做（只做文本级注入 + 后端有界历史）；非本批必需。
- P3（Stop/中断、会话搜索、真流式、成本显示、Inspector raw_evidence）、P4（债务 + Track A Beta 邀请 + re-tag）未动。
