# S74 竞品机制与产品收敛基线

**状态**：ACTIVE research baseline  
**日期**：2026-06-09  
**目的**：在继续删除或重建核心路径前，用公开、可查证的成熟产品机制校准 Asteria。

## 1. 调研结论

Claude Code、Codex 和 OpenCode 的共同方向不是“用 Runtime 状态机穷举模型行为”，而是：

1. 以连续 Session / Thread 承载目标、过程、结果和后续追问。
2. 让模型在工具 observation 返回后继续决定下一步。
3. 在工具和不可逆动作边界执行权限、沙箱与审批。
4. 把 Plan、Review、Debug 作为可选择的模式或显式动作，而不是默认恢复流水线。
5. 用项目指导、按需读取、compact/resume 和隔离子任务管理上下文。
6. 用真实工具过程、diff、验证和最终总结建立用户信任。

因此，Asteria 的差异化应建立在本地优先、可审计证据、多 provider、candidate/promotion
和长任务持续性上，而不是建立更多内部阶段、固定角色和重复恢复控制器。

## 2. Claude Code

公开机制：

- 权限架构在编辑文件、运行命令等动作前请求许可，用户可单次或持续批准。
- Hook 围绕 `PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop`、`PreCompact`、
  `SessionStart` 等真实生命周期边界扩展。
- 项目、用户和组织指导通过分层 memory 文件进入上下文；子目录指导按需发现。
- 子 Agent 使用独立上下文窗口和受限工具，完成任务后把结果返回主会话。
- compact、resume 和 session transcript 支撑长会话连续性。

Asteria 应吸收：

- 权限与确定性控制放在动作边界。
- 失败和 hook 反馈回到当前模型循环。
- 子 Agent 是按需隔离委派，不是固定角色流水线。
- 上下文是分层、按需和可压缩的。

不应复制：

- 专有 prompt、内部实现或 UI 像素。
- 把所有 Claude Code 命令机械复制成 Asteria 命令。

## 3. Codex

公开产品与当前应用机制强调：

- 用户给出目标，Agent 在同一线程中探索、修改、验证并汇报。
- 工具执行、修改文件、测试和最终结果在会话中连贯呈现。
- AGENTS 指导按工作区层级约束工作方式。
- 审批、沙箱和受保护操作控制执行风险。
- Review、diff 和 Inspector 用于查证，用户可以在同一任务上继续追问。
- 长任务通过 durable goal、线程和可验证操作延续，而不是要求用户操作内部状态机。

Asteria 应吸收：

- 主会话必须让用户看见系统实际做了什么。
- Inspector 服务于证据查验，不抢占主叙事。
- 最终回答稳定表达结果、验证和开放风险。
- 项目指导是 Agent 工作契约，不是面向用户的运行面板。

## 4. OpenCode

公开机制：

- Session 是核心连续对象；主 Agent 可通过 Task 工具调用子 Agent。
- Plan、Build 等 Agent/mode 通过 prompt、model 和 permission 区分能力。
- permission 统一表达 `allow | ask | deny`，可按工具、命令模式和 Agent 覆盖。
- 被禁止的子 Agent 可直接从 Task 工具说明中隐藏，减少模型无效尝试。
- Skill 是模型按需加载的复用指导，并受 permission 约束。

Asteria 应吸收：

- 能力差异优先用 prompt、工具可见性和 permission 表达。
- 用户模式不等于固定执行阶段。
- 子 Agent 调用走普通受控工具边界。
- 工具和 Skill 按需发现，避免把完整能力目录常驻上下文。

## 5. 产品与架构裁决

| 主题 | 裁决 |
| --- | --- |
| 固定全局状态机 | 不作为产品架构；仅保留少量恢复状态字段 |
| TaskGraph / Coordinator 默认主导 | 冻结；只有真实多任务依赖需求和 eval 收益才启用 |
| Run 自动 Review -> Debug -> Replan | 删除；恢复回到当前 Session Agent Loop |
| 独立 Debug 修复执行器 | 替换为显式诊断模式或当前 Session 的受限继续 |
| 固定 Agent 类流水线 | 冻结；按需子 Agent 用 prompt + tools + permission 表达 |
| 全局 Runtime completeness gate | 删除；风险在动作边界，质量由 verification/eval 判断 |
| Studio 内部状态面板主导 | 删除；主窗口只讲用户目标推进，Inspector 查证 |
| 合成成功 evidence | 删除；partial/timeout 必须保持真实状态 |
| candidate/promotion/merge | 保留；它是本地可审计与安全交付差异化 |
| 多 provider | 保留；以实际 route 健康和用户可用性校准 |

## 6. 下一批执行计划

### Batch A：恢复链归一

- 审计并替换 `DebugCommand` 的独立修复执行责任。
- 删除 `goal_policy` 的重复语义投影。
- 把 explicit review 保持为证据、反馈和 diff 查验。

完成标准：默认失败只回到当前 Session；显式 debug 不产生第二套隐藏编排。

### Batch B：Session 与报告解耦

- 从 Run 私有方法提取稳定的 session result/report service。
- Resume、Accept、Studio 共用同一事实，不互相调用命令私有实现。
- 删除重复的 runtime/user progress 投影。

完成标准：一份真实 Session transcript 驱动 CLI、Studio 和恢复。

### Batch C：Context 与 Capability 收敛

- 建立指导、最近 Session、按需文件、Skill/MCP、子任务摘要的唯一装配路径。
- 删除重复 capability catalog 和全量常驻 prompt。
- 用真实任务测量上下文体积、重复率和 compact 后恢复质量。

完成标准：上下文更小且真实任务成功率不下降。

### Batch D：真实 Beta 校准

- 跑 3-5 个真实小任务：代码修改、文档更新、诊断、显式 review、一次子任务。
- 记录首次有效工具时间、工具间延迟、总耗时、模型调用、恢复和验证结果。
- 优先删除造成延迟和认知负担但没有成功率收益的层。

完成标准：用户只看主会话即可判断进展；Inspector 可查证；失败可在同一 Session 继续。

## 7. 官方来源

- Claude Code memory: https://docs.claude.com/en/docs/claude-code/memory
- Claude Code security: https://docs.claude.com/en/docs/claude-code/security
- Claude Code hooks: https://docs.claude.com/en/docs/claude-code/hooks
- Claude Code subagents: https://docs.claude.com/en/docs/claude-code/sub-agents
- Codex use cases: https://developers.openai.com/codex/explore
- OpenCode permissions: https://opencode.ai/docs/permissions
- OpenCode agents: https://opencode.ai/docs/agents/
- OpenCode skills: https://opencode.ai/docs/skills

这些来源用于学习公开机制，不代表复制专有实现。每个后续 Slice 必须记录采用了哪一项
机制、解决什么真实摩擦，以及不复制什么。
