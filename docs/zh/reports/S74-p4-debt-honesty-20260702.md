# S74 P4 债务/诚实化（本批）落地（2026-07-02）

> 承接 `S74-full-system-claims-audit-20260702.md` §3 的 P4「债务与放量前提」。用户选「只做可直接改的债务 /
> 诚实文档降级」，Track A 外部 Beta 邀请与 re-tag v0.2.0a2 作为里程碑决策**不在本批**。先派 6 代理钉当前代码 +
> 分类 code_fix / honesty_doc / do_not_touch_blocked / milestone（1 个 agent 撞 StructuredOutput 上限失败，见 P4-e 自评）。

## 侦察纠正的审计数字（诚实）

- **mypy 实为 83 错 / 18 文件，非审计的 129**；其中 51（61%）锁在 `real_provider_matrix.py`+`real_model_smoke.py`（real_model 栈 DO_NOT_TOUCH），55% 是 `union-attr` optional-none 噪音（非崩溃 bug）；真正可修且值得修的非锁 code_fix 约 30 错。
- **schema 漂移 17 处，非 18**，且 `test_schema_packaging.py` 的 `KNOWN_SCHEMA_CONTENT_DRIFT` 精确守门（0 意外、测试绿）。7 处纯 CRLF/空白语义相等，10+ 处真语义漂移**双向**（小 schema root 是超集，goal_spec/task 反而 packaged 更新）——不可盲目单向 copy。
- **JsonlStore fail-open→fail-closed 其实已落地**（`rewrite_all`/`json_store.write` 均逐行 schema 校验 + 原子 tmp→replace）；审计此条已过时，本批仅诚实标注、0 代码。

## 本批做了什么（4 项 code_fix/honesty_doc，均非 DO_NOT_TOUCH）

### P4-a init 幂等（code_fix, `init_command.py` + `cli.py`）
- 根因：`_write_json` 对 project.json/policies.json/root_snapshot.json/backlog.json 一律 `store.write` 覆盖为默认值（只区分 created/updated 不跳过）；`self.force` 被存却全程不读 → `--force` 是 no-op；唯 AGENTS.md 有 exists 守卫，与「不覆盖用户手写内容」验收对不齐。
- 修法：`_write_json` 加 `preserved` 参 —— 已存在且 `not self.force` → 跳过写入并记 preserved；`--force` 才重生成。使 `--force` 从 no-op 变真生效。同步改 cli.py 的 `--force` help 文案对齐真语义。
- 测试：+2（重跑保留用户改过的 policies.json 且入 preserved；`--force` 重生成覆盖用户改动）。

### P4-b 文档超卖批改（honesty_doc，5 文档 + cli help 常量）
- ① `架构设计.md` fork 从「用户命令」降级标「设计意图、当前未实现（全仓无 fork 代码）」。
- ② `大模型循环与动态上下文设计.md` + `成本安全与风险.md`：把「near-limit 触发 compact / 压缩上下文」降级为「写可恢复快照 + 建议裁剪，当前只测量+建议、不自动缩减 live 上下文」；标注 `phase_boundary_compaction`/`handoff_compaction` 为预留旗标、运行时未消费。
- ③ `cli.py` MODEL_STRATEGY_HELP：`local` 从「reserved for privacy-first local routes」降级为「路由偏好占位、未接入实际本地路由、回落默认档」（注意与真 provider 别名 `AGENT_MODEL_PROVIDER=local` 是两回事，未误伤）。
- ④ `成本安全与风险.md`：`max_total_minutes` 加旁注「声明性字段、运行时未强制墙钟；BudgetController 只强制 model/tool/iteration/repair 预算与 context pressure」。

### P4-c session_id 恒 null 诚实化（code_fix, `user_progress_logger.py`）
- 根因：`UserProgressLogger.record()` 写 `session_id=self.session_id`，但全部 20+ 调用点无一传 session_id → 每条 user_progress 事件 session_id 恒 null。运行时本无独立「会话」概念（session==run、run_dir==session_dir）。
- 修法：`session_id` 改为 `self.session_id or run_id` —— 未显式绑会话时落 run 自身 id 作会话身份，消除恒 null 且不撒谎；显式绑定仍优先。仅动 logger 一行（非 DO_NOT_TOUCH），schema 已允许 string。测试 +1。

### P4-f 死 MCP server 炸 run（code_fix, `mcp_adapter.py`）
- 根因：`from_configs` 急切构造 `StdioMcpSession`（`subprocess.Popen`），命令不存在 → FileNotFoundError 在构造期抛出，越过只包 `discover_tools` 的 try，经无守卫的 `_wire_mcp_adapter` 中止整个 run；与 `架构设计.md:201`「死 server 降级为无工具」声称相反。
- 修法：`from_configs` 每个 session 构造包 `try/except OSError` → spawn 失败跳过该 server（不入 sessions dict）。`invoke_tool` 对缺失 session 已返结构化 `mcp_server_not_configured`、`discover_tools` 只遍历 live sessions → 干净降级为「无该 server 工具」，令文档声称成真。仅动 `mcp_adapter.py`（非 DO_NOT_TOUCH），ValueError（空命令）保留为显式配置错误。测试 +1。

## 验证
- backend：`pytest tests/unit` **902 passed**（+2 本批）+ `tests/integration/test_init_command.py` 14 passed（+2）；`ruff check src tests` clean；`test_documentation_contracts` 22 passed；`test_cli` 绿（help 文案改动无回归）。
- 未触碰 execute/run/gate/acceptance·real_model 栈。

## 明确不做 / DecisionPoint / defer（诚实边界）

- **schema 漂移同步**：双向漂移必须逐 schema 定权威副本 + 验 producer 满足更严副本，盲目单向 copy 会放松校验放非法持久化对象过关（正是 P0-1 修过的类漏洞）→ **defer 为专项 DecisionPoint**，本批不动。
- **real_model 栈 mypy 51 错**：撞 DO_NOT_TOUCH（禁重构）→ 治理走 DecisionPoint 或 per-module ignore 配置决策，本批不动。
- **真写 Studio 会话 id 全链路**（P4-c 理想根治）：需 server.mjs→cli.py→run_command/execute_command 穿参，后两者 DO_NOT_TOUCH → **DecisionPoint**。本批只做 logger `or run_id` 消除 null。
- **P4-e memory_lesson_reuse 自断言剧场 / review 计分深度 / run_command usage 自动 pass**：修法多落 real_model_acceptance / acceptance_gate / run_command（DO_NOT_TOUCH）→ **honesty 标注 + DecisionPoint**；本批未改（该项 recon agent 撞 StructuredOutput 上限失败，未取得精确定位，留后续）。
- **P4-c server 披露**（run_id_source 标注、user_progress tail-120 截断 total/flag）：S–M、需前端同步才可见，**留小follow-up**，非本批必需。
- **纠错**：recon 报 `validation_run_command.py:781/789` 为「set 赋给 list[str] 真类型 bug」经复核为**误报**——两处均 set 推导式、`worker_ids <= succeeded_worker_ids` 是集合子集、逻辑正确，未改。
- **里程碑**：Track A 外部 Beta 邀请、re-tag v0.2.0a2 —— 门槛（P0+P1 完成）已满足，属对外/发布决策，等用户拍板，不在本批。
