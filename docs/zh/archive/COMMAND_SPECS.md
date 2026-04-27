# 多智能体自主开发系统 - 命令规格

## 1. 文档目的

本文档定义系统初始命令的输入、输出、权限、状态变化、产物和失败处理。

命令不是 prompt 快捷方式，而是可复用、可观测、可审计的工作流。

## 2. 通用命令结构

每个命令都应定义：

- 名称。
- 目的。
- 输入参数。
- 读取上下文。
- 允许工具。
- 参与智能体。
- 状态变化。
- 输出产物。
- 成本预算。
- 失败处理。
- 是否允许 agent 自行调用。

通用执行流程：

```text
parse command
  -> load root guidance
  -> load relevant memory
  -> check permissions and budget
  -> run command workflow
  -> write artifacts
  -> update event log
  -> update task state
  -> summarize result
```

## 3. `/init`

### 目的

将目录初始化为 agent-ready 工作区。

### 输入

```text
/init
/init --force
/init --profile planning|codebase|empty
```

### 读取上下文

- 当前目录结构。
- Git 状态。
- README、package 文件、配置文件。
- 已存在的 `AGENTS.md` 和 `.agent/`。

### 允许工具

- `list_files`
- `read_file`
- `search_code`
- `write_file`
- `create_directory`
- `detect_project`
- `write_event`

### 输出产物

- `AGENTS.md`
- `.agent/project.json`
- `.agent/policies.json`
- `.agent/context/root_snapshot.json`
- `.agent/tasks/backlog.json`

### 失败处理

- 如果存在用户手写内容，不覆盖，创建建议补丁。
- 如果项目类型无法判断，标记为 `unknown` 并生成 `DecisionPoint`。
- 如果没有 Git 仓库，允许继续，但记录限制。

### Agent 自调用

默认不允许。通常由用户或首次运行流程触发。

## 4. `/plan`

### 目的

将用户目标转化为结构化目标规格和任务计划。

### 输入

```text
/plan "做一个密码测试工具"
/plan --from goal_spec.json
```

### 读取上下文

- `AGENTS.md`
- `.agent/project.json`
- 用户目标。
- 相关记忆。
- 当前任务看板。

### 参与智能体

- GoalSpecAgent
- PlannerAgent
- ProductAgent 可选

### 输出产物

- `.agent/runs/<run_id>/goal_spec.json`
- `.agent/runs/<run_id>/task_plan.json`
- `.agent/tasks/backlog.json`

### 验收

- 目标不再只是原句复述。
- 至少包含完成定义。
- 至少包含验证策略。
- 对模糊目标给出合理假设。

### 失败处理

- 目标过于模糊时创建 `DecisionPoint`。
- 无法生成任务时输出阻塞原因。

### Agent 自调用

允许，但必须在新目标或重大变更后调用。

## 5. `/brainstorm`

### 目的

对宽泛、创意型或欠规格目标进行发散和收敛。

### 输入

```text
/brainstorm "个人自动化工具"
/brainstorm --goal goal_spec.json --max-candidates 8
```

### 参与智能体

- ProductAgent
- ResearchAgent 可选
- UXExperienceAgent 可选

### 输出产物

- `brainstorm_report.md`
- `candidate_ideas.json`
- 可选 `DecisionPoint`
- 可选任务或实验。

### 流程

```text
generate candidates
  -> cluster
  -> score
  -> select recommendation
  -> create tasks or decision points
```

### 评分维度

- 用户目标匹配度。
- 可行性。
- 实现成本。
- 使用价值。
- 风险。
- 新颖性。
- 验证难度。

### 失败处理

- 候选过多时压缩为 3-5 个方向。
- 方向差异过大时创建用户决策点。

### Agent 自调用

允许，但受预算限制。

## 6. `/research`

### 目的

将外部资料、论文、开源项目或行业实践转化为可执行假设。

### 输入

```text
/research "密码强度测试工具常见功能"
/research --goal goal_spec.json
```

### 允许工具

- `query_web`
- `query_docs`
- `read_file`
- `write_memory`
- `create_task`

### 输出产物

- `research_notes.md`
- `claims.json`
- `hypotheses.json`
- `source_list.json`
- 实现任务或实验任务。

### 质量要求

- 观点必须带来源或明确标记为模型推断。
- 调研必须转化为任务、实验、约束或决策点。
- 不允许只输出泛泛摘要。

### Agent 自调用

允许，但默认需要预算许可；联网调研可由策略禁用。

## 7. `/compact`

### 目的

压缩上下文，支持长任务续航和智能体交接。

### 输入

```text
/compact
/compact focus on UI decisions
/compact prepare handoff for ReviewerAgent
```

### 输出产物

- `.agent/context/snapshots/<timestamp>.json`
- 可选 `handoff.md`

### 必须保留

- 目标。
- 完成定义。
- 用户决策。
- 活跃任务。
- 修改文件。
- 验证结果。
- 失败修复。
- 未解决风险。
- 下一步行动。

### 不应保留

- 大段原始日志。
- 可从磁盘读取的大文件内容。
- 已经无关的讨论。

### Agent 自调用

允许。达到上下文阈值时可自动调用。

## 8. `/decide`

### 目的

创建用户决策点。

### 输入

```text
/decide "这个工具应该做成 Web App 还是 CLI?"
```

### 输出产物

- `decision_point.json`
- 事件日志记录。
- 项目记忆记录。

### 决策请求必须包含

- 问题。
- 推荐选项。
- 2-4 个选择。
- 每个选择的取舍。
- 默认选择。
- 对预算、范围、风险、质量的影响。

### Agent 自调用

允许，但只能用于重大决策。

## 9. `/review`

### 目的

评审代码、需求覆盖、UX、测试和风险。

### 输入

```text
/review
/review --diff
/review --ux
/review --requirements
```

### 输出产物

- `review_report.md`
- `findings.json`
- 可选修复任务。

### 评审维度

- 正确性。
- 需求覆盖。
- 测试充分性。
- 安全风险。
- 体验问题。
- 范围膨胀。
- 可维护性。

### Agent 自调用

允许。合并或 keep 前必须调用。

## 10. `/debug`

### 目的

分析失败并提出最小修复。

### 输入

```text
/debug --last-failure
/debug --command "npm test"
```

### 输出产物

- `failure_summary.md`
- `repair_hypotheses.json`
- 可选修复 patch。

### 流程

```text
collect evidence
  -> summarize failure
  -> generate hypotheses
  -> choose minimal fix
  -> rerun verification
```

### Agent 自调用

允许，但受最大修复次数限制。

## 11. `/handoff`

### 目的

为另一个智能体或未来运行创建续接包。

### 输入

```text
/handoff
/handoff --to ReviewerAgent
```

### 输出产物

- `handoff.md`
- `handoff.json`
- 最新 `ContextSnapshot`

### 必须包含

- 当前目标。
- 当前状态。
- 活跃任务。
- 已接受决策。
- 最近 diff。
- 验证状态。
- 风险。
- 推荐下一步。

### Agent 自调用

允许。上下文压缩或委派前可调用。

## 12. 命令预算建议

默认预算：

```yaml
init:
  model_calls: 2
  tool_calls: 30
plan:
  model_calls: 4
  tool_calls: 20
brainstorm:
  model_calls: 4
  tool_calls: 20
research:
  model_calls: 6
  tool_calls: 40
compact:
  model_calls: 1
  tool_calls: 10
review:
  model_calls: 3
  tool_calls: 30
debug:
  model_calls: 4
  tool_calls: 30
handoff:
  model_calls: 1
  tool_calls: 10
```

超过预算时应：

1. 尝试压缩上下文。
2. 降级模型。
3. 减少候选数量。
4. 请求用户批准继续。
