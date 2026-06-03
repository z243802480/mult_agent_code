# ADR-0006: Main Path over Internal Gate Surface

日期：2026-06-03

## 背景

Asteria 已经具备 AgentLoopDecision、RuntimeReadinessGate、route/deadline、context/capability、worker/subagent、promotion/recovery 等证据链。继续把这些内部对象直接放到默认用户界面，会让产品越来越像维护者控制台，而不是自主开发运行时。

Claude Code 的成熟产品思路值得吸收：用户默认看到的是一个简洁的 coding loop：理解目标、计划/待办、使用工具、验证、必要时修复或询问、最后停止并交付。权限、hook、security、tool policy 是执行边界，不是普通用户每天必须理解的主屏概念。

## 决策

默认产品面采用固定主路径：

```text
Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop
```

Runtime 继续保留内部 evidence 和 gate，但默认 `status`、final report、run loop summary、Studio 主屏和 chat context 必须优先展示 `main_path`：

- `active_stage`：当前处在 plan_todo、tool_use、verify、repair、ask、stop 哪一步。
- `current_step`：用户或模型下一步真正要做什么。
- `next_command`：如果需要用户操作，只给一个可执行命令。
- `permission_boundary`：只展示权限模式，不展开内部 policy。
- `maintainer_refs`：把 raw evidence、route timeline、run summary 留给 Inspector/maintainer。

## 约束

- 不为了展示主路径新增 gate。
- 不让历史失败、route guidance 或 provider 细节驱动默认 next step。
- 不隐藏证据；只把 raw evidence 移到 maintainer/Inspector 层。
- Repair/Ask/Stop 是恢复出口，不是失败细节枚举器。
- Tool permission 和 sandbox 仍由 Runtime 执行边界控制，不能靠模型文本承诺替代。

## 结果

- 用户心智稳定为：目标 -> 计划/待办 -> 工具执行 -> 验证 -> 修复/询问/停止。
- `status` / final report / chat / Studio 可以消费同一个 `main_path` 对象。
- `gate-status`、`capability-report`、route timeline、schema refs、raw JSONL 继续作为维护者诊断面。
- 后续新增机制必须先说明它落在主路径哪一步；如果只能解释内部状态，默认不进入用户主屏。
