# ADR-0004: 适应性 Gate 保留 Agent 灵活性

> 2026-06-09 校正：本 ADR 的动作边界原则继续有效；全局 `RuntimeReadinessGate` 已由
> ADR-0013 删除。Context/capability/evidence 缺口进入诊断或验证，不再形成全局 Runtime block。

## 状态

Accepted

## 背景

Asteria 需要学习 Claude Code、Codex、opencode 等优秀编程 agent 产品的共同设计：模型/agent 在探索、阅读、推理、局部试验和修复中应保持足够自由；Runtime 在权限、写入、成本、上下文、验证和交付边界上提供可靠护栏。

项目的特色是长任务 Runtime OS：可恢复、可审计、可控成本、可验证交付。因此 Asteria 会比交互式编程 agent 保留更多 durable evidence、schema 和 gate。但这些约束不能扩散成“所有输出材料都必须预先合格”的形式，否则会损失 agent 的创造力、调试弹性和真实开发速度。

## 决策

采用适应性 gate，而不是全局强 gate。

默认原则：

1. 探索阶段保持灵活：读文件、搜索、分析、提出候选方案、readonly child worker、fake-path planner、局部假设和失败后的 debug/replan 只需要轻量 trace，不要求每一步都满足最终交付材料格式。
2. 风险边界强 gate：写入主工作区、promotion、merge、rollback、远程 push、删除/覆盖、跨 workspace 读写、真实 provider 放量、预算 hard-stop、发布/验收交付必须经过明确 gate。
3. Gate 要保护不可逆风险，而不是替代模型判断：Runtime 负责阻断污染、越权、失控成本和不可恢复状态；模型仍负责在能力边界内选择方案、拆任务、修复和收敛。
4. Gate 结果要可解释：阻断时必须给出下一步恢复路径，例如 approve/reject/discard/retry、repair/replan、compact、补验证或降级执行。
5. 产品前台不暴露内部复杂度：普通用户看到 goal、progress、artifact、decision、verification 和 next step；maintainer 才需要 raw gate-status、schema refs 和 evidence bundle。

## 分层策略

| 层级 | 默认策略 | 示例 |
| --- | --- | --- |
| Readonly / exploration | 宽松，记录轻量 trace | read/search/list、readonly fanout、候选方案、失败归因 |
| Candidate / fake path | 中等约束，要求结构化但允许试错 | child planner、fake-path disjoint write gate、候选 workspace 验证 |
| Promotion / merge | 强 gate，必须可阻断和可恢复 | candidate promotion、merge gate、write_scope、verification evidence |
| Release / remote / irreversible | 最强 gate，需要明确授权和完整证据 | push、发布、删除、rollback、预算 hard-stop、真实 provider 放量 |

## 后果

- `disjoint_write_workers` 的严格 gate 只应用在真实并行写 worker 放量、candidate promotion 和 readiness/release 判断上；不应把普通 planner 输出或 readonly/fake-path 探索变成繁重审批。
- ContextBudgetMeter 与 capability audit 应优先解释风险与恢复路径，而不是增加不必要的阻塞项；全局 RuntimeReadinessGate 已删除。
- 新增 gate 前必须说明它保护的风险类型、适用阶段、恢复路径，以及为什么不会削弱 agent 在低风险阶段的发挥。
- 当 gate 影响真实开发速度时，优先考虑降级为 review、warning、light trace 或 maintainer-only 检查，而不是默认 blocked。

## 回滚或替代条件

如果真实小任务灰度显示 gate 导致 agent 频繁停在无风险环节，应收窄 gate 适用范围；如果真实并行写入、promotion 或发布出现污染风险，应加强对应风险边界的 gate，而不是扩大到所有 agent 输出。
