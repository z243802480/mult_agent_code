# S74 全系统复杂度审计裁决

日期：2026-06-09  
状态：S74 execution verdict  
依据：ADR-0010、ADR-0011、ADR-0012、ADR-0013、ADR-0014、ADR-0015、
`S74_REFERENCE_PRODUCT_BASELINE.md`

## 裁决原则

审计单位是完整责任链，不是单个文件。每项能力只允许一个默认控制器；动作安全在动作边界执行；
模型失败结果回到当前 Session；评审与验证只查证，不充当第二 orchestrator；真实 Beta/eval 不得合成成功。
连续 Session Agent Loop 是产品架构；状态机、TaskGraph 和固定 Agent 类不构成愿景，
只按真实消费者和配对 eval 裁决。

## 完整裁决矩阵

| 子系统 | 能力裁决 | 当前实现裁决 | 唯一正确责任 | 下一动作 |
| --- | --- | --- | --- | --- |
| 默认 Session Agent Loop | KEEP_CORE | REPLACE_IMPLEMENTATION | model -> tool -> observation -> model | 持续减少 Runtime 语义代决策 |
| JSON action / native tool_use | KEEP opt-in | OPT_IN | provider transport adapter | 配对真实 Eval 前不扩大默认 |
| schema/action retry | KEEP_CORE | TRIM | provider/action parser 边界 | 只修格式，不做任务语义 repair |
| task/tool/verification repair | KEEP_CORE | REPLACE_IMPLEMENTATION | 当前 Session Agent Loop | observation 直接回流，不启第二执行器 |
| DebugCommand / DebugAgent | KEEP capability | REPLACE_IMPLEMENTATION | 显式诊断 + 向当前 Session 注入恢复反馈 | 删除独立 repair engine，改薄适配器 |
| ReplanCommand | KEEP explicit | FREEZE | 用户或 Agent Loop 显式 replan 动作 | 禁止由 Review/Run 后置触发 |
| ReviewCommand / ReviewAgent | KEEP_CORE | TRIM | 显式查证、反馈、接受前检查 | 禁止创建任务、DecisionPoint、AgentLoopDecision |
| AcceptCommand | KEEP_CORE | REPLACE_IMPLEMENTATION | 显式接受、promotion、不可逆边界 | 移除对 RunCommand 私有报告方法的调用 |
| Goal policy / goal_policy.json | DELETE concept | REPLACE_IMPLEMENTATION | active next step + pending DecisionPoint | 删除同义投影与 Studio/Status 映射 |
| user_progress Session Transcript | KEEP_CORE | KEEP/COMPLETE | 用户语义过程真源 | 补生产侧缺失事件 |
| runtime_progress / main_path / summaries | KEEP diagnostics | TRIM | CLI/Inspector/恢复辅助 | 禁止重建 Studio 主会话 |
| legacy events.jsonl | KEEP_PLACEHOLDER | FREEZE | 兼容/Inspector | 不新增产品语义消费者 |
| real-model smoke/gate/acceptance | KEEP_CORE | REPLACE_IMPLEMENTATION | 严格观察真实结果 | 禁止伪造 eval/review/final 或超时成功 |
| subagent / worker / L3 | KEEP opt-in | FREEZE | 明确委派、隔离、父子 evidence | 真实收益前不扩大默认 |
| parallel writes | KEEP opt-in | FREEZE | disjoint workspace + merge/promotion | 保持 Beta opt-in |
| candidate workspace / merge / promotion | KEEP_CORE | TRIM | 写入与不可逆边界 | 审计重复状态机，但不削弱安全 |
| context envelope/package/budget/compact | KEEP_CORE | REPLACE_IMPLEMENTATION | session context + scoped child context + compact | 删除多套压力判断和重复复制 |
| capability/tool/MCP/skill catalog | KEEP_CORE | REPLACE_IMPLEMENTATION | 按需发现 + 声明式权限 | 删除重复目录和 prompt 全量注入 |
| Studio Thread / Inspector | KEEP_CORE | REPLACE_IMPLEMENTATION | Thread 讲过程，Inspector 查证 | 不从内部 evidence 猜主会话 |
| maintainer gate/validation/acceptance shells | HIDE_NOT_DELETE | FREEZE/MERGE | CI/release preflight | 无独立价值入口合并，不进默认 UX |
| schemas/JSONL/report | KEEP by consumer | DELETE by reachability | 稳定生产者 + 稳定消费者 | 无真实消费者和迁移价值即删除 |
| deferred Agent / aliases / fallback | DELETE by reachability | DELETE | 无 | 禁止保留备用实现 |

## 已执行批量清算

1. 删除 RuntimeReadinessGate 全局总闸门。
2. 删除默认 Run 的自动 Review/Debug/Replan/Goal-policy 重入。
3. 删除 Review 创建 follow-up task、DecisionPoint 和 AgentLoopDecision。
4. 删除无人消费的 FollowUpTaskPlanner 与 keyword DecisionPolicy。
5. 删除 real-model smoke/gate/acceptance 的超时成功 salvage 和伪造 review/eval/final。
6. Studio 主会话改为 Session Transcript 单一真源。

## 后续执行批次

### Batch A：恢复执行器归一

- 将 `DebugCommand` 从独立 repair engine 改为显式诊断/恢复适配器。
- 复用 Execute Agent Loop、tool gateway、candidate workspace 和 observation evidence。
- 删除 DebugCommand 内重复的工具执行、验证、候选推广和任务状态机。

验收：显式 debug 仍可解释失败并继续当前 Session；默认 Run、Review 不依赖 DebugCommand。

### Batch B：产品状态真源归一

- 删除 `goal_policy.json` 及 Status/Sessions/Studio 的 goal_policy 投影。
- 统一使用 active next step、pending DecisionPoint、run status 和 Session Transcript。
- 将报告生成从 `RunCommand` 私有方法抽为独立 report service，Accept/Resume 不再调用 Run 私有方法。

验收：同一下一步只存在一个产品语义来源；Accept/Resume 不实例化 Run 只为调用私有 helper。

### Batch C：上下文与能力目录归一

- 绘制 ContextEnvelope、context package、budget snapshot、compact 的唯一生产/消费图。
- 删除重复 token pressure 和无人消费 snapshot。
- 工具/MCP/skill/capability 采用按需发现，禁止默认 prompt 全量复制。

验收：每个 context/capability 对象存在稳定生产者和消费者，并证明减少 prompt/维护成本。

### Batch D：编排与运维壳收缩

- subagent/L3/parallel writes 保持 opt-in，以 3–5 个真实任务配对收益裁决。
- 合并重复 maintainer shell；删除无真实消费者 schema/report/fallback。
- 保留动作边界、安全 evidence 和 release preflight。

验收：默认产品路径不受实验编排与 maintainer 壳影响；删除对象通过 reachability 与 paired eval 证明。

## 禁止事项

- 禁止新增后置恢复控制器、全局完整性 Gate 或 keyword 语义路由。
- 禁止用“测试需要”保留无产品消费者的实现。
- 禁止 smoke/acceptance 在真实结果缺失时合成成功。
- 禁止在完成当前 Batch 前切换到新编排 Wave 或无 friction 证据的 Studio 功能。
