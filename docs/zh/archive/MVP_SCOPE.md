# 多智能体自主开发系统 - MVP 范围与阶段路线图

## 1. 文档目的

本文档定义第一版 MVP 的交付边界、阶段路线图和需求保留策略。

核心原则：

- 可以分阶段实现。
- 不能因为 MVP 收窄就随意删除有价值需求。
- 暂缓的需求必须进入路线图或风险处理计划。
- 高风险能力必须在设计层给出控制机制，而不是只记录风险。
- 成本控制是系统能力的一部分，不是上线后再补的运维问题。

## 2. MVP 定位

MVP 的目标不是一次性完成完整多智能体平台，而是验证最关键的 agent harness 闭环：

```text
初始化项目
  -> 接收目标
  -> 生成目标规格
  -> 扩展基本需求
  -> 拆解任务
  -> 执行实现
  -> 运行验证
  -> 自动修复
  -> 保留或丢弃
  -> 压缩上下文
  -> 输出最终报告
```

MVP 成功后，系统应证明：

- 不是一步指令执行器。
- 能处理模糊目标。
- 能自动补全合理需求。
- 能通过工具产出真实文件。
- 能运行验证并根据结果修复。
- 能用日志和报告解释自己做了什么。

## 3. MVP 必做能力

### 3.1 CLI 入口

必须支持：

- `agent run "<goal>"`
- `agent init`
- `agent plan`
- `agent compact`
- `agent review`

MVP 可以先不做完整本地 Web 控制台。

### 3.2 `/init` 初始化

必须创建：

- `AGENTS.md`
- `.agent/project.json`
- `.agent/policies.json`
- `.agent/context/root_snapshot.json`
- `.agent/tasks/backlog.json`
- `.agent/runs/`
- `.agent/memory/`

必须具备幂等性，重复运行不能覆盖用户手写内容。

### 3.3 目标规格化

必须生成 `goal_spec.json`，包含：

- 原始目标。
- 推断需求。
- 假设。
- 非目标。
- 完成定义。
- 验证策略。
- 预算限制。

### 3.4 基础需求扩展

必须能对简单模糊目标做合理补全。

示例：

```text
输入：做一个密码测试工具
系统应扩展出：强度评分、策略检查、隐私说明、输入反馈、基础测试、运行说明
```

MVP 不要求复杂联网调研，但可以使用模型内置知识和可选的 Web 调研工具。

### 3.5 任务看板

必须支持任务状态：

- `backlog`
- `ready`
- `in_progress`
- `testing`
- `reviewing`
- `done`
- `blocked`
- `discarded`

### 3.6 单工作区执行

MVP 可以先使用一个临时工作区或当前工作区的受控写入模式。

必须支持：

- 记录修改文件。
- 生成 diff。
- 失败时回滚或标记失败。

### 3.7 工具注册表

MVP 必须提供：

- 文件读取。
- 文件搜索。
- 补丁应用。
- 命令运行。
- 测试运行。
- 事件记录。

### 3.8 基础自动纠错

必须支持：

- 捕获失败输出。
- 总结失败。
- 生成修复假设。
- 应用最小修复。
- 重新运行验证。
- 超过次数后停止。

默认限制：

```text
max_retries_per_task: 2
max_total_repair_attempts: 5
rollback_on_regression: true
```

### 3.9 上下文压缩

必须支持 `/compact`。

压缩必须保留：

- 当前目标。
- 已接受决策。
- 活跃任务。
- 修改文件。
- 验证结果。
- 失败修复。
- 下一步行动。

### 3.10 最终报告

必须生成 `final_report.md`，包含：

- 目标。
- 扩展需求。
- 用户决策。
- 完成任务。
- 文件改动。
- 验证结果。
- 失败和修复。
- 成本摘要。
- 剩余风险。
- 下一步建议。

## 4. MVP 暂缓能力

以下能力不能删除，但可以暂缓：

- 多智能体并发。
- Git worktree 合并队列。
- 完整 Web dashboard。
- 完整论文调研和引用系统。
- 高级向量记忆。
- PDF 生成。
- UI screenshot 自动检查。
- 插件市场。
- 分布式实验执行。
- 多项目长期知识图谱。

这些能力进入 V1/V2/V3 路线图。

## 5. 阶段路线图

### Phase 0：文档和规格冻结

目标：

- 明确 MVP 边界。
- 明确命令规格。
- 明确数据模型。
- 明确评估和测试策略。
- 明确成本和风险控制策略。

产物：

- `MVP_SCOPE.md`
- `COMMAND_SPECS.md`
- `EVALUATION.md`
- `TEST_STRATEGY.md`
- `COST_AND_RISK.md`

### Phase 1：单 agent harness

目标：

- 实现最小运行时。
- 支持 `/init`、`/plan`、`/compact`。
- 支持单 CoderAgent。
- 支持工具调用日志。

验收：

- 能在空目录初始化。
- 能生成目标规格和任务。
- 能修改文件。
- 能输出运行报告。

### Phase 2：验证和自动修复

目标：

- 接入测试命令。
- 接入失败分析。
- 接入最小修复循环。
- 接入 keep/discard。

验收：

- 给定一个可复现失败，系统能尝试修复。
- 修复失败时能停止并报告。
- 成功时能记录保留原因。

### Phase 3：需求扩展和决策管理

目标：

- 接入 `/brainstorm`。
- 支持模糊目标需求扩展。
- 支持 `DecisionPoint`。
- 支持决策颗粒度配置。

验收：

- 对“密码测试工具”这类模糊目标能生成合理需求。
- 遇到重大分支能询问用户。
- 常规实现细节不打扰用户。

### Phase 4：Research 和 UI/Experience

目标：

- 接入基础调研工作流。
- 接入 UI/Experience 输出判断。
- 支持 Web/CLI/报告等输出形态建议。

验收：

- 能把调研结论转成任务。
- 能解释为什么选择某种输出形态。

### Phase 5：多 agent 和工作区隔离

目标：

- 支持多个 agent 并行。
- 支持 Git worktree。
- 支持评审和合并队列。

验收：

- 多个 agent 不互相覆盖文件。
- 合并前必须通过验证和评审。

## 6. 需求保留策略

每个需求都应处于以下状态之一：

- `mvp`: MVP 必做。
- `v1`: MVP 后第一阶段。
- `v2`: 中期能力。
- `v3`: 长期能力。
- `research`: 需要继续调研。
- `blocked`: 依赖外部条件。

不能使用“删除”作为默认处理方式。

如果需求风险过高，应转化为：

- 权限控制。
- 预算限制。
- 人类决策点。
- 沙箱隔离。
- 验证门禁。
- 灰度启用。

## 7. MVP 默认策略

推荐默认配置：

```yaml
decision_granularity: balanced
max_iterations_per_goal: 8
max_repair_attempts_per_task: 2
max_total_tool_calls: 120
max_total_model_calls: 60
context_compaction_threshold: 0.75
allow_network_research: false
allow_shell: true
allow_destructive_shell: false
allow_global_install: false
```

这些默认值后续可以由 `.agent/policies.json` 覆盖。
