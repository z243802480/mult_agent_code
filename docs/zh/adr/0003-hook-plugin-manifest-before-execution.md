# ADR-0003: 插件先声明后执行

## 状态

Accepted

## 背景

Asteria 需要吸收 Claude Code、opencode、Codex 等工程化 agent runtime 的扩展思想，但项目非目标明确禁止 unrestricted agent chatroom 和绕过权限边界的工具执行。插件比 skill 风险更高，可能触发 hook、工具、网络、shell 或报告导出，因此不能直接开放执行。

## 选项

- 立即允许本地插件代码执行：迭代快，但安全、日志、权限、超时和回滚都不成熟。
- 先实现 HookPolicy、PluginManifest 和只读控制面：扩展速度较慢，但能先形成 schema、诊断、权限声明和审计主键。

## 决策

插件体系分阶段推进：

1. Manifest 阶段：读取并校验 `.asteria/plugins/*.plugin.json`，不执行代码。
2. Internal handler 阶段：只允许内置或测试 handler 验证 hook policy、脱敏、超时和审计。
3. Local plugin 阶段：在 policy、权限声明、超时、错误隔离和诊断成熟后再执行本地插件。
4. Marketplace 阶段：签名、版本兼容、禁用列表、回滚和用户确认成熟后再考虑。

## 后果

- `hooks.plugins_enabled=false` 是默认值。
- `PluginManifest`、`RuntimeHookEvent`、`plugins doctor`、`doctor/status/package-check` 是插件执行前的必要控制面。
- 外部插件执行前必须补 threat model、ErrorTaxonomy、handler timeout 和版本兼容策略。

## 回滚或替代条件

如果插件控制面导致 alpha 用户困惑，应继续保持插件 metadata-only，并把扩展能力先落到内置 tools 或 skills，而不是开放执行。
