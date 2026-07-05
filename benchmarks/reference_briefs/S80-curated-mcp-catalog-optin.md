# S80 — 内置精选 MCP 目录（opt-in）+ DebugAgent 决定

Reference-first brief。授权：2026-07-05 用户"调研主流 agent 默认项，选择性地带一些贴合场景；DebugAgent 你据主流自定"。

## 机制学习（不重造轮子）

- **Claude Code**：不默认捆绑 MCP server，全靠 `claude mcp add` / `.mcp.json` / 插件；官方参考仓 `modelcontextprotocol/servers` 7 个，6 离线（filesystem/git/memory/sequential-thinking/time/everything）仅 fetch 联网。skill/slash-command 是过程模型；插件 = skills+MCP+hooks 的 opt-in 集合。
- **Cursor**：无默认 MCP，`~/.cursor/mcp.json` 配置、默认关。**Aider**：不发 MCP。**OpenCode**：内置 shell/edit/web-fetch/web-search/LSP。**Codex-rs**：仓库工具为主。
- 结论：主流默认姿态就是"零默认 + 显式添加 + 诚实标注"。我们照此，不硬塞。

## 与我们定位的对齐（纠偏点）

本地优先/离线/国产化/安全敏感 + ADR-0016 ⇒ 主流推荐清单大半不该默认开：
- `sequential-thinking` 违背 ADR-0016（推理外包给固定脚手架）→ 目录含但标"不推荐"、默认关。
- `memory` 与 `.asteria` 重叠；`filesystem`/`git` 与原生工具重叠 + 首用 npx/uvx 联网。
- 真新能力仅 `fetch`（联网）→ opt-in + 告警 + 需可信网络策略。

## 交付（DoD）

1. `templates/mcp_catalog.json`（双份同步）：6 server × {command, reaches_network, requires_runtime, recommended, notes} + 顶层 runtime_note。
2. `asteria mcp {list,enable,disable}`（`mcp_command.py` 镜像 plugins）：只改 `policies.json` `mcp.servers`；live 路径本就读它。
3. 出厂 `mcp.servers=[]` 不变（离线/安全零回归）。
4. DebugAgent：维持 KEEP_PLACEHOLDER 不动（主流+ADR-0014/0016 同形，debug=skill+自主 repair 环已落地）。
5. ADR-0019 + 测试 `test_mcp_command.py`（10）+ 全绿 1209/1skip、ruff/mypy/doc_contracts 净。

## 非目标

- 不捆绑 server 实现本体（仍经 npx/uvx 拉取）；不默认开任何 server；不复活 S69 对抗验证器/独立 DebugAgent（仍冻结，需另 ADR）。
