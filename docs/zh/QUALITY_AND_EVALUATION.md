# 多智能体自主开发系统 - 质量、评估与测试

## 1. 文档目的

本文档定义系统如何判断“任务完成得好不好”，以及如何测试这套 agent runtime。

系统不能只依赖模型自评。评估体系必须结合：

- 结构化验收条件。
- 自动测试。
- 运行结果。
- 代码和产物评审。
- 用户决策。
- 成本和轨迹评估。

## 2. 评估分层

```text
Goal Eval：目标是否被正确理解和扩展
Artifact Eval：产物是否存在、可运行、可阅读
Outcome Eval：最终结果是否满足目标
Trajectory Eval：执行过程是否健康、经济、可恢复
Cost Eval：成本是否适度且有效
```

## 3. Goal Eval

指标：

- `goal_clarity_score`
- `requirement_expansion_score`
- `assumption_quality_score`
- `definition_of_done_score`
- `decision_point_quality_score`

最低验收：

```text
goal_clarity_score >= 0.75
definition_of_done_score >= 0.75
```

## 4. Artifact Eval

检查：

- 是否生成目标规格。
- 是否生成任务计划。
- 是否生成运行日志。
- 是否生成代码或报告等目标产物。
- 是否生成最终报告。
- 是否记录工具调用。
- 是否记录成本摘要。

失败条件：

- 只生成聊天摘要，没有文件产物。
- 修改文件但没有记录原因。
- 没有最终报告。

## 5. Outcome Eval

通用指标：

- `requirement_coverage`
- `verification_pass_rate`
- `usability_score`
- `documentation_score`
- `safety_score`
- `run_success`

建议最低验收：

```text
requirement_coverage >= 0.70
verification_pass_rate >= 0.80
documentation_score >= 0.60
safety_score >= 0.80
```

## 6. Trajectory Eval

指标：

- `loop_count`
- `repair_success_rate`
- `tool_relevance_score`
- `scope_drift_score`
- `decision_noise_score`
- `cost_efficiency_score`
- `rollback_correctness`

危险信号：

- 反复修改同一文件但没有验证改善。
- 绕过测试。
- 频繁扩大范围。
- 不断调用模型但没有产物。
- 频繁询问用户小问题。
- 出现高风险操作但没有决策点。

## 7. Cost Eval

指标：

- 模型调用次数。
- 估算 token。
- 工具调用次数。
- 运行时间。
- 每个任务平均成本。
- 每个成功 patch 成本。
- 无产物调用比例。

建议阈值：

```yaml
max_model_calls_per_goal_mvp: 60
max_tool_calls_per_goal_mvp: 120
max_repair_attempts_per_task: 2
max_no_artifact_model_call_ratio: 0.25
```

## 8. 用户决策评估

指标：

- `critical_decision_recall`
- `minor_question_rate`
- `decision_packet_quality`

一个合格决策包必须包含：

- 问题。
- 推荐。
- 选项。
- 取舍。
- 默认行为。
- 影响说明。

## 9. 自迭代评估

系统必须证明自己不是一步执行器。

指标：

- 是否发现缺失需求。
- 是否创建后续任务。
- 是否基于验证结果调整计划。
- 是否在达到可用基线后停止。

失败条件：

- 用户说“密码测试工具”，系统只做一个输入框评分。
- 没有评估“是否好用”。
- 没有基于评审创建改进任务。

## 10. 验收分级

### Pass

- 核心需求满足。
- 验证大部分通过。
- 成本在预算内。
- 风险已说明。
- 有最终报告。

### Partial

- 主要产物存在。
- 有部分需求未覆盖。
- 有失败但已解释。
- 可以进入下一轮迭代。

### Fail

- 无可用产物。
- 目标理解错误。
- 验证完全缺失。
- 产物不可运行且未说明。
- 成本失控。

## 11. 测试金字塔

```text
Unit Tests
  -> Schema Tests
  -> Tool Tests
  -> Command Workflow Tests
  -> Agent Loop Tests
  -> End-to-End Scenario Tests
  -> Regression Benchmarks
```

## 12. 单元测试

覆盖：

- 数据模型。
- 状态机转换。
- 预算计算。
- 权限判断。
- 任务状态更新。
- 决策颗粒度判断。
- 上下文压缩选择逻辑。

## 13. Schema 测试

核心对象必须校验：

- `GoalSpec`
- `Task`
- `DecisionPoint`
- `ContextSnapshot`
- `Experiment`
- `RunReport`
- `CostReport`
- `ProjectConfig`
- `PolicyConfig`

## 14. 工具测试

每个工具都必须测试：

- 成功路径。
- 失败路径。
- 权限拒绝。
- 日志记录。
- 输出结构。
- 超时。

## 15. 命令工作流测试

必须覆盖：

- `/init`
- `/plan`
- `/brainstorm`
- `/compact`
- `/debug`
- `/review`
- `/handoff`

## 16. Agent Loop 测试

测试闭环：

```text
goal
  -> plan
  -> implement
  -> verify
  -> repair
  -> review
  -> report
```

必须覆盖：

- 正常完成。
- 验证失败后修复成功。
- 修复失败后停止。
- 用户决策后继续。
- 上下文压缩后继续。
- 成本接近阈值后降级。

## 17. 端到端场景

### 17.1 密码测试工具

期望：

- 自动扩展需求。
- 识别隐私和安全边界。
- 生成可运行工具。
- 有基础测试。
- 有最终报告。

### 17.2 Markdown 知识库

期望：

- 生成导入、索引、搜索、问答任务。
- 输出合适 UI 形态建议。
- 至少实现 MVP 子集。

### 17.3 批量文件重命名工具

期望：

- 形成 CLI/桌面/Web 决策点。
- 默认保护文件安全。
- 支持预览再执行。

### 17.4 修复已有项目

期望：

- 自动运行测试。
- 定位失败。
- 尝试最小修复。
- 通过后生成 diff 和报告。

### 17.5 上下文长任务续航

期望：

- 压缩后不丢失目标、任务、决策。
- 后续阶段能继续。

## 18. 回归基准集

```text
benchmarks/
  password_tool/
  markdown_kb/
  file_renamer/
  failing_tests_project/
  long_context_project/
```

每个 benchmark 包含：

- 输入目标。
- 初始文件。
- 期望产物。
- 验收脚本。
- 预算限制。
- 预期报告片段。

## 19. 模型不稳定性测试策略

不比较完整自然语言输出。优先使用：

- Schema 校验。
- 关键字段检查。
- 产物存在检查。
- 命令退出码。
- 测试通过率。
- 语义评分。
- 稳定部分的快照测试。

真实模型专项检查：

- `model-check` 验证 provider 配置、端点、认证和基础 JSON 响应。
- 端到端 smoke 使用临时目录，检查目标产物、session 日志和最终报告。
- `agent acceptance` 必须持久化 `acceptance_report.json`，让验收通过/失败都可被后续 runtime 读取。
- `agent acceptance --promote-failures` 必须把失败场景转换为当前 session 的可执行修复任务，并避免重复生成同一场景任务。
- 新 promoted failure 必须记录为 `failure_lesson` memory，避免真实模型失败经验只存在于一次性日志里。
- `agent acceptance --run-promoted` 必须是显式开关；默认不得自动触发真实模型执行成本。
- 结构化输出测试覆盖 `<think>`、markdown code fence、近似 JSON、字段别名和少量 schema drift。
- 无法安全归一化的输出必须被阻塞或进入修复流程，不能静默当作成功。
- 验证命令归一化集中在 `verification_command_normalizer.py`；只改写已知低风险测试夹具命令，不可证明安全的命令必须保持原样交给 shell policy 拦截。
- 网络超时、TLS EOF、429/5xx 等链路抖动通过有限重试验证，不能无限重试。

## 20. MVP 测试完成定义

最低条件：

- `/init` 测试通过。
- `/plan` 测试通过。
- `/compact` 测试通过。
- 至少 2 个端到端场景通过。
- 成本阈值测试通过。
- 安全权限测试通过。
- 失败修复测试至少一个通过。
