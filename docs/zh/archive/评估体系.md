# 多智能体自主开发系统 - 验收指标与评估体系

## 1. 文档目的

本文档定义系统如何判断“任务完成得好不好”。

系统不能只依赖模型自评。评估体系必须结合：

- 结构化验收条件。
- 自动测试。
- 运行结果。
- 代码和产物评审。
- 用户决策。
- 成本和轨迹评估。

## 2. 评估分层

系统评估分为四层：

```text
Goal Eval：目标是否被正确理解和扩展
Artifact Eval：产物是否存在、可运行、可阅读
Outcome Eval：最终结果是否满足目标
Trajectory Eval：执行过程是否健康、经济、可恢复
```

## 3. Goal Eval

用于评估目标规格化和需求扩展。

指标：

- `goal_clarity_score`：目标是否被清晰结构化。
- `requirement_expansion_score`：是否合理补全缺失需求。
- `assumption_quality_score`：假设是否明确且不过度。
- `definition_of_done_score`：完成定义是否可验证。
- `decision_point_quality_score`：重大分支是否被识别。

最低验收：

```text
goal_clarity_score >= 0.75
definition_of_done_score >= 0.75
```

## 4. Artifact Eval

用于评估产物是否真实存在且结构正确。

检查项：

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

用于评估最终产物是否满足目标。

通用指标：

- `requirement_coverage`：需求覆盖率。
- `verification_pass_rate`：验证通过率。
- `usability_score`：可用性评分。
- `documentation_score`：文档完整度。
- `safety_score`：安全边界是否清晰。
- `run_success`：是否能实际运行。

建议最低验收：

```text
requirement_coverage >= 0.70
verification_pass_rate >= 0.80
documentation_score >= 0.60
safety_score >= 0.80
```

## 6. Trajectory Eval

用于评估智能体执行过程是否健康。

指标：

- `loop_count`：是否出现无效循环。
- `repair_success_rate`：修复尝试成功率。
- `tool_relevance_score`：工具调用是否相关。
- `scope_drift_score`：是否偏离目标。
- `decision_noise_score`：是否过度打扰用户。
- `cost_efficiency_score`：成本是否合理。
- `rollback_correctness`：失败是否正确回滚。

危险信号：

- 反复修改同一文件但没有验证改善。
- 绕过测试。
- 频繁扩大范围。
- 不断调用模型但没有产物。
- 频繁询问用户小问题。
- 出现高风险操作但没有决策点。

## 7. Cost Eval

成本评估是验收的一部分。

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

如果超过阈值，系统必须：

- 压缩上下文。
- 降低候选数量。
- 降级模型。
- 停止低价值分支。
- 请求用户批准继续。

## 8. 用户决策评估

决策机制要评估两个方向：

- 是否漏掉重大决策。
- 是否过度打扰用户。

指标：

- `critical_decision_recall`：重大决策识别率。
- `minor_question_rate`：小问题打扰比例。
- `decision_packet_quality`：决策包质量。

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

## 10. 评估报告格式

每次运行结束应生成：

```json
{
  "goal_eval": {},
  "artifact_eval": {},
  "outcome_eval": {},
  "trajectory_eval": {},
  "cost_eval": {},
  "decision_eval": {},
  "overall": {
    "status": "pass|partial|fail",
    "score": 0.82,
    "reason": "usable but missing UI screenshot check"
  }
}
```

## 11. 验收分级

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

## 12. MVP 验收用例

### 用例 1：初始化规划工作区

输入：

```text
/init
```

期望：

- 创建根指导文件。
- 创建 `.agent/`。
- 生成初始上下文。
- 不覆盖已有用户内容。

### 用例 2：模糊目标扩展

输入：

```text
做一个密码测试工具
```

期望：

- 生成扩展需求。
- 识别安全和隐私边界。
- 至少生成 5 个合理任务。
- 生成完成定义。

### 用例 3：失败修复

输入：

```text
运行一个包含失败测试的项目
```

期望：

- 捕获失败。
- 生成假设。
- 尝试修复。
- 重新验证。
- 成功则保留，失败则停止并报告。

### 用例 4：上下文压缩续航

输入：

```text
/compact prepare handoff
```

期望：

- 生成 ContextSnapshot。
- 保留目标、任务、决策、验证和下一步。
- 新 agent 能基于快照继续。

### 用例 5：重大决策交互

输入：

```text
做一个批量文件工具
```

期望：

- 在 Web/CLI/桌面工具之间形成决策点。
- 提供推荐和取舍。
- 用户选择后写入记忆。
