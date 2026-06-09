# ADR-0015：连续 Session Agent Loop 是产品架构

**状态**：Accepted  
**日期**：2026-06-09

## 背景

早期架构把 Runtime 控制平面、TaskGraph、固定 Agent 类和全局状态机写成系统中心。这些
对象有助于描述内部实现，却容易让 Runtime 替模型决定语义步骤、形成重复恢复链，并让
Studio 展示内部状态而不是用户任务进展。

Claude Code、Codex 和 OpenCode 的公开机制共同表明，成熟 Agent 产品主要依靠连续
Session、模型工具循环、动作边界权限、上下文压缩、显式用户动作和真实证据完成驾驭。

## 决策

1. Asteria 的产品架构以连续 Session Agent Loop 为中心。
2. Runtime 在动作边界执行权限、沙箱、预算、持久化和 promotion，不默认决定语义下一步。
3. 状态字段只服务于持久化、恢复和查证，不构成用户工作流或模型执行脚本。
4. Plan、Review、Debug、Accept 是显式交互动作或模式，不是默认自动恢复流水线。
5. 子 Agent 是受控工具式委派，不是固定角色流水线。
6. Studio 主窗口只展示用户任务进展；内部状态和原始 evidence 留在 Inspector。

## 后果

- 删除或替换与 Session Agent Loop 重复的恢复控制器和投影。
- 新机制必须有竞品公开机制参考、真实 friction、可测收益和清晰退出条件。
- 文档和代码不得再次把固定状态机、TaskGraph 或 Coordinator 描述为产品中心。
- Asteria 的自研差异化继续保留在本地优先证据、多 provider、candidate/promotion 和
  长任务连续性，但其实现必须接受成熟产品机制和真实任务评估。
