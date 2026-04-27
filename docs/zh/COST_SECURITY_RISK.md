# 多智能体自主开发系统 - 成本、安全与风险治理

## 1. 文档目的

本文档定义系统如何控制 API 成本、工具成本、时间成本、安全风险和工程风险。

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

- 模型调用次数。
- 输入 token。
- 输出 token。
- 长上下文消耗。
- 强模型调用比例。

### 3.2 工具成本

- Shell 命令执行。
- 测试运行。
- 构建运行。
- 浏览器截图。
- Web 调研。
- 文件扫描。

### 3.3 时间成本

- 单任务执行时长。
- 自动修复轮数。
- 等待用户决策时间。
- 长任务总体时长。

### 3.4 认知成本

- 用户被打扰次数。
- 用户需要阅读的决策包数量。
- 最终报告复杂度。

## 4. 默认预算策略

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

## 7. 默认安全策略

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

## 8. 安全控制

### 8.1 路径保护

默认保护：

- `.env`
- `secrets/`
- `.git/`
- 私钥文件。
- 凭证文件。

### 8.2 Shell 命令分级

```text
safe：读取、测试、构建、格式化
risky：安装依赖、修改大量文件、网络访问
blocked：删除大量文件、全局安装、远程推送、部署生产
```

### 8.3 网络访问

默认关闭。联网调研或外部 API 必须由策略开启，或通过用户决策点批准。

### 8.4 Secrets 检测

文件读取和报告生成前应避免泄露：

- API key。
- token。
- 私钥。
- 密码。
- cookie。

## 9. 风险分类与设计控制

### 9.1 目标偏离

风险：

智能体自主扩展需求时偏离用户真实目标。

设计控制：

- 使用 `GoalSpec`。
- 记录假设。
- 重大范围扩展进入 `DecisionPoint`。
- 评估 `scope_drift_score`。

### 9.2 成本爆炸

设计控制：

- 全局预算。
- 每命令预算。
- 每 agent 预算。
- 上下文压缩。
- 强模型路由限制。
- 超预算前暂停。

### 9.3 幻觉调研

设计控制：

- 来源记录。
- claim/evidence 分离。
- 无来源内容标记为推断。
- 关键结论进入验证或决策。

### 9.4 破坏代码库

设计控制：

- 工作区隔离。
- diff 审查。
- 回滚机制。
- 高风险文件保护。
- 合并前验证。

### 9.5 过度打扰用户

设计控制：

- 决策颗粒度配置。
- 小问题自动默认。
- 只对重大分支询问。
- 记录 `minor_question_rate`。

### 9.6 不询问重大决策

设计控制：

- Decision Manager。
- 重大决策检测信号。
- 隐私/安全/预算/范围扩展默认升级。

### 9.7 自动修复循环失控

设计控制：

- 最大修复次数。
- 修复前后指标对比。
- 无改善则回滚。
- 生成阻塞报告。

### 9.8 多 agent 冲突

设计控制：

- 单 agent MVP。
- 后续 Git worktree。
- 文件 ownership。
- 合并队列。
- ReviewerAgent。

### 9.9 安全和隐私

设计控制：

- 受保护路径。
- 网络权限配置。
- 外部服务决策点。
- 本地优先默认。
- secrets 检测。

## 10. 风险处理状态

每个风险应标记：

- `designed`
- `mitigated`
- `accepted`
- `blocked`
- `needs_research`

不能只写“有风险”，必须有处理状态和负责人。

## 11. 运行时成本报告

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
