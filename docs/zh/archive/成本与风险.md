# 多智能体自主开发系统 - 成本控制与风险治理

## 1. 文档目的

本文档定义系统如何控制 API 成本、工具成本、时间成本和工程风险。

成本控制不是简单省钱，而是保证 token、工具调用和智能体迭代能转化为有效产物。

## 2. 成本目标

系统应追求：

```text
适度调用
高产物率
低空转
可解释成本
可配置预算
超预算前可降级或停止
```

即使包年 API 调用量充足，也不能允许爆炸式占用。

## 3. 成本类型

### 3.1 模型成本

包括：

- 模型调用次数。
- 输入 token。
- 输出 token。
- 长上下文消耗。
- 强模型调用比例。

### 3.2 工具成本

包括：

- Shell 命令执行。
- 测试运行。
- 构建运行。
- 浏览器截图。
- Web 调研。
- 文件扫描。

### 3.3 时间成本

包括：

- 单任务执行时长。
- 自动修复轮数。
- 等待用户决策时间。
- 长任务总体时长。

### 3.4 认知成本

包括：

- 用户被打扰次数。
- 用户需要阅读的决策包数量。
- 最终报告复杂度。

## 4. 默认预算策略

MVP 默认预算：

```yaml
goal_budget:
  max_model_calls: 60
  max_tool_calls: 120
  max_total_minutes: 30
  max_iterations: 8
  max_repair_attempts_total: 5
  max_repair_attempts_per_task: 2
  max_research_calls: 5
  max_user_decisions: 5

context:
  compaction_threshold: 0.75
  hard_stop_threshold: 0.90

model_routing:
  planning: strong
  architecture: strong
  coding: medium
  review: strong
  summarization: cheap
  classification: cheap
```

## 5. 成本降级策略

当接近预算时，系统应按顺序执行：

1. 压缩上下文。
2. 减少 brainstorm 候选数量。
3. 停止低价值分支。
4. 降级非关键模型。
5. 合并相似任务。
6. 减少自动修复次数。
7. 请求用户批准继续。
8. 生成阶段性报告并暂停。

## 6. 成本异常检测

危险信号：

- 模型调用很多但没有文件产物。
- 重复读取同一大文件。
- 反复运行同一失败测试但没有修复。
- 多个 agent 做重复调研。
- 长时间 brainstorm 没有收敛。
- 上下文接近上限但未压缩。

触发后系统必须：

- 写入事件日志。
- 总结异常原因。
- 尝试压缩和收敛。
- 必要时创建 `DecisionPoint`。

## 7. 风险分类

### 7.1 目标偏离

风险：

智能体自主扩展需求时偏离用户真实目标。

设计控制：

- 使用 `GoalSpec`。
- 记录假设。
- 重大范围扩展进入 `DecisionPoint`。
- 评估 `scope_drift_score`。

### 7.2 成本爆炸

风险：

多 agent、长上下文、反复修复导致调用失控。

设计控制：

- 全局预算。
- 每命令预算。
- 每 agent 预算。
- 上下文压缩。
- 强模型路由限制。
- 超预算前暂停。

### 7.3 幻觉调研

风险：

ResearchAgent 生成看似合理但无依据的结论。

设计控制：

- 来源记录。
- claim/evidence 分离。
- 无来源内容标记为推断。
- 关键结论进入验证或决策。

### 7.4 破坏代码库

风险：

自动修改导致项目不可恢复。

设计控制：

- 工作区隔离。
- diff 审查。
- 回滚机制。
- 高风险文件保护。
- 合并前验证。

### 7.5 过度打扰用户

风险：

系统频繁问小问题，降低自主性。

设计控制：

- 决策颗粒度配置。
- 小问题自动默认。
- 只对重大分支询问。
- 记录 `minor_question_rate`。

### 7.6 不询问重大决策

风险：

系统擅自决定技术栈、输出形式或隐私策略。

设计控制：

- Decision Manager。
- 重大决策检测信号。
- 隐私/安全/预算/范围扩展默认升级。

### 7.7 自动修复循环失控

风险：

系统不断尝试修复但没有进展。

设计控制：

- 最大修复次数。
- 修复前后指标对比。
- 无改善则回滚。
- 生成阻塞报告。

### 7.8 多 agent 冲突

风险：

多个 agent 修改同一文件或产生冲突设计。

设计控制：

- 单 agent MVP。
- 后续 Git worktree。
- 文件 ownership。
- 合并队列。
- ReviewerAgent。

### 7.9 安全和隐私

风险：

读取敏感文件、调用外部服务、泄露本地数据。

设计控制：

- 受保护路径。
- 网络权限配置。
- 外部服务决策点。
- 本地优先默认。
- secrets 检测。

## 8. 风险处理状态

每个风险应标记：

- `designed`: 已有设计控制。
- `mitigated`: 已在实现中缓解。
- `accepted`: 明确接受。
- `blocked`: 阻塞交付。
- `needs_research`: 需要调研。

不能只写“有风险”，必须有处理状态和负责人。

## 9. 运行时成本报告

每次运行必须输出：

```json
{
  "model_calls": 34,
  "tool_calls": 82,
  "estimated_input_tokens": 120000,
  "estimated_output_tokens": 18000,
  "strong_model_calls": 8,
  "cheap_model_calls": 12,
  "repair_attempts": 2,
  "context_compactions": 1,
  "user_decisions": 2,
  "cost_status": "within_budget"
}
```

## 10. 默认安全策略

MVP 默认：

```yaml
allow_network: false
allow_shell: true
allow_destructive_shell: false
allow_global_package_install: false
allow_secret_file_read: false
allow_remote_push: false
allow_deploy: false
```

需要突破默认策略时必须创建 `DecisionPoint`。
