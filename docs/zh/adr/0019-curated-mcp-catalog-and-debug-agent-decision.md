# ADR-0019：内置精选 MCP 目录（opt-in）+ DebugAgent 维持 deferred 的决定

- 状态：Proposed（2026-07-05）
- 关联：[研发总计划 §16.1 line 467 生态部分]、[ADR-0016 认知归模型/边界归状态]、[ADR-0014 单会话恢复与显式 review]、[[product-positioning-internal-engine]]、`mcp_command.py`、`templates/mcp_catalog.json`、`agents/debug_agent.py`
- 授权：2026-07-05 用户指令——调研主流 agent（Claude Code 那类）的默认项，"选择性地带一些，贴合我们使用场景"；DebugAgent 方向由本方据主流自行决定。

## 1. 背景（Context）

两处审计缺口（`S77-commercial-readiness-audit` P2 生态）：**零默认 MCP server、无 add-server UX**。核实底盘现状：`mcp_adapter.py` 已是**真实现**（真 subprocess 起 stdio/JSON-RPC、与 skill 同构接入 `mcp__server__tool` 工具面、同一套 capability/budget gate + `mcp_invocations.jsonl` + 真 subprocess 冒烟测试）。唯一缺的是"默认带哪些 server"（`policies.default.json` `mcp.servers=[]`）与启用入口。

调研两条主流事实（子代理 web 调研签字）：
1. **Claude Code 自身也不默认捆绑任何 MCP server**——全靠 `claude mcp add` / `.mcp.json` 用户显式添加；官方 7 个参考 server 里 6 个离线，仅 `fetch` 联网。
2. debug 在 Claude Code / OpenCode / Cursor / Aider **均非自主 agent**，而是模型跟一份过程（skill/slash-command）用读写测工具做。

对照我们自己的定位（[[product-positioning-internal-engine]]：本地优先、离线可用、国产化栈、安全敏感）与 ADR-0016，主流"推荐清单"里大半**不该默认开**：`sequential-thinking` 把推理外包给固定脚手架，**直接违背 ADR-0016**；`memory` 与 `.asteria` 持久化重叠；`filesystem`/`git` 与原生工具重叠且平添 npx/uvx 首用联网依赖。真正带来新能力的只有 `fetch`（但联网）。

## 2. 决策（Decision）

### 2a. MCP：内置**精选目录 + opt-in 启用**，出厂全 disabled

- 新增 `templates/mcp_catalog.json`（**双份**：仓库根 `/templates/` 与 `src/asteria_runtime/templates/`，遵 [[schema-dir-runtime-vs-packaged]] 双份约束）：6 个参考 server（git/fetch/filesystem/time/memory/sequential-thinking），每条**诚实标注** `reaches_network`、`requires_runtime`、`recommended`、`notes`（含与原生/架构的重叠与 ADR-0016 冲突警示）。顶层 `runtime_note` 明说这些经 npx/uvx 首用会联网拉包、故默认关以保离线姿态。
- 新增 `asteria mcp {list,enable,disable}` 命令（`mcp_command.py`，镜像 `plugins_command.py` 形态）：`list` 只读展示目录 + 当前启用态 + 联网告警；`enable/disable` **只**改 workspace `policies.json` 的 `mcp.servers` 列表。live execute 路径本就读这份列表（`_wire_mcp_adapter → mcp_adapter_config_from_policy`），故启用即在下次 run 接入模型工具面。
- **出厂零行为变更**：`mcp.servers=[]` 不动，fresh run 仍不碰任何 MCP、保持离线/安全。启用是操作者显式、诚实（联网项 list 即告警）的选择。

### 2b. DebugAgent：**维持 deferred placeholder，不新建独立 agent**

- 主流一致 + 我们的 ADR-0014（运行时无自动 Gate→Repair DebugAgent，repair/replan 是 CoderAgent 单循环内的显式模型动作）+ ADR-0016（认知归模型）**三者同形**。本会话已落地的 debug 能力恰是主流形态：`skills/bundled/debug/SKILL.md`（过程）+ 已闭合的自主 repair/replan 环（[[freeze-lifted-autonomous-loop]]）。
- 故 `agents/debug_agent.py` **保持现状**：triage 锁的 KEEP_PLACEHOLDER，不扩回 live 环、不删除。其 docstring 已诚实标注"NOT wired / deferred"——无超卖，无需改动。
- S69"对抗验证器"作为独立能力**不在本决定内复活**；若未来要做需另立 ADR + DecisionPoint（仍冻结）。

## 3. ADR-0016 合规映射

- **认知归模型**：不引入 `sequential-thinking` 类推理脚手架为默认；debug 归模型跟 skill，不归独立状态机 agent。
- **边界归状态**：MCP 的联网/权限/预算是**边界**，显式化为 catalog 的诚实标注 + capability gate + list 告警 + 默认关。启用是人审边界动作。

## 4. 回滚（Rollback）

- MCP：删 `mcp_command.py` + cli.py 三处接线 + 两份 `mcp_catalog.json` + 测试即全回退；`policies.json` 里已启用的 server 是普通配置，删命令不影响运行时读取（仍可手改 policy）。无 schema 迁移、无 flag。
- DebugAgent：本决定不改代码，无回滚项。

## 5. 一致性检查（Conformance）

- `tests/unit/test_mcp_command.py`：目录精选且诚实（每条有 network 姿态/notes）、默认全 off、enable 写入且运行时可解析、幂等、联网告警、未知名拒绝、workspace 自定义 server 也显性、未初始化拒绝。
- 出厂 `mcp.servers=[]` 不变 → 既有 MCP 测试与 run 零影响。
