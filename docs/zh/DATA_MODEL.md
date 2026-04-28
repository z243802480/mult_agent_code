# 多智能体自主开发系统 - 数据模型

## 1. 文档目的

本文档定义系统核心数据对象、状态枚举、文件落盘位置和 schema 约定。

目标：

- 让运行时、命令、智能体、工具和评估系统共享同一套结构化语言。
- 减少靠自然语言传递状态造成的歧义。
- 支持长任务续航、上下文压缩、任务恢复和审计。
- 为后续代码实现提供直接的数据结构依据。

## 2. 通用约定

### 2.1 Schema 版本

每个持久化对象必须包含：

```json
{
  "schema_version": "0.1.0"
}
```

版本规则：

- patch：字段说明、非破坏性默认值调整。
- minor：新增可选字段。
- major：字段删除、字段含义改变或结构破坏性变更。

### 2.2 ID 约定

推荐 ID 格式：

```text
run-20260427-0001
goal-0001
task-0001
decision-0001
exp-0001
artifact-0001
event-0001
agent-0001
toolcall-0001
memory-0001
```

ID 应在单个项目内唯一。

### 2.3 时间格式

所有时间使用 ISO 8601：

```text
2026-04-27T14:30:00+08:00
```

### 2.4 状态字段

状态字段必须使用枚举，不使用自由文本。

自由文本应放到：

- `summary`
- `reason`
- `notes`
- `description`

### 2.5 文件路径

路径使用项目根目录相对路径：

```json
{
  "path": "src/main.py"
}
```

禁止在持久化对象中默认写入机器相关绝对路径，除非对象是本机运行日志。

## 3. 目录映射

推荐落盘结构：

```text
AGENTS.md
.agent/
  project.json
  policies.json
  context/
    root_snapshot.json
    snapshots/
    handoffs/
  tasks/
    backlog.json
  runs/
    run-20260427-0001/
      run.json
      goal_spec.json
      task_plan.json
      events.jsonl
      tool_calls.jsonl
      model_calls.jsonl
      experiments.jsonl
      decisions.jsonl
      artifacts.jsonl
      cost_report.json
      eval_report.json
      final_report.md
  memory/
    project_memory.jsonl
    user_memory.jsonl
    research_memory.jsonl
    experiment_memory.jsonl
```

## 4. ProjectConfig

文件：

```text
.agent/project.json
```

用途：

记录项目级元数据和 agent 入口信息。

```json
{
  "schema_version": "0.1.0",
  "project_id": "project-0001",
  "name": "mult-agent-code",
  "workspace_type": "planning_workspace",
  "created_at": "2026-04-27T14:30:00+08:00",
  "updated_at": "2026-04-27T14:30:00+08:00",
  "languages": ["markdown"],
  "frameworks": [],
  "package_managers": [],
  "commands": {
    "install": null,
    "run": null,
    "test": null,
    "lint": null,
    "typecheck": null,
    "build": null,
    "format": null
  },
  "important_paths": ["docs/", "docs/zh/"],
  "protected_paths": [".env", "secrets/", ".git/"],
  "root_guidance_path": "AGENTS.md",
  "default_policy_path": ".agent/policies.json"
}
```

枚举：

```text
workspace_type:
  empty_workspace
  planning_workspace
  codebase
  mixed
  unknown
```

## 5. PolicyConfig

文件：

```text
.agent/policies.json
```

用途：

记录预算、安全、决策颗粒度和工具策略。

```json
{
  "schema_version": "0.1.0",
  "decision_granularity": "balanced",
  "budgets": {
    "max_model_calls_per_goal": 60,
    "max_tool_calls_per_goal": 120,
    "max_total_minutes_per_goal": 30,
    "max_iterations_per_goal": 8,
    "max_repair_attempts_total": 5,
    "max_repair_attempts_per_task": 2,
    "max_research_calls": 5,
    "max_user_decisions": 5
  },
  "context": {
    "compaction_threshold": 0.75,
    "hard_stop_threshold": 0.9
  },
  "permissions": {
    "allow_network": false,
    "allow_shell": true,
    "allow_destructive_shell": false,
    "allow_global_package_install": false,
    "allow_secret_file_read": false,
    "allow_remote_push": false,
    "allow_deploy": false
  },
  "model_routing": {
    "planning": "strong",
    "architecture": "strong",
    "coding": "medium",
    "review": "strong",
    "summarization": "cheap",
    "classification": "cheap"
  }
}
```

枚举：

```text
decision_granularity:
  autopilot
  balanced
  collaborative
  manual
```

## 6. Run

文件：

```text
.agent/runs/<run_id>/run.json
```

用途：

记录一次运行的总状态。

```json
{
  "schema_version": "0.1.0",
  "run_id": "run-20260427-0001",
  "goal_id": "goal-0001",
  "status": "running",
  "started_at": "2026-04-27T14:30:00+08:00",
  "ended_at": null,
  "entry_command": "agent run \"做一个密码测试工具\"",
  "current_phase": "PLAN",
  "workspace": {
    "mode": "single_workspace",
    "path": "."
  },
  "summary": ""
}
```

枚举：

```text
run.status:
  queued
  running
  paused
  blocked
  completed
  failed
  cancelled

current_phase:
  INIT
  SPEC
  PLAN
  BRAINSTORM
  DECIDE
  RESEARCH
  DESIGN
  IMPLEMENT
  VERIFY
  REVIEW
  REPAIR
  KEEP_OR_DISCARD
  MEMORY_UPDATE
  REPORT
  DONE
  BLOCKED
```

## 7. GoalSpec

文件：

```text
.agent/runs/<run_id>/goal_spec.json
```

用途：

结构化用户目标。

```json
{
  "schema_version": "0.1.0",
  "goal_id": "goal-0001",
  "original_goal": "做一个密码测试工具",
  "normalized_goal": "构建一个本地优先的密码测试与辅助工具",
  "goal_type": "software_tool",
  "assumptions": [
    "用户希望工具本地运行",
    "默认不把密码发送到外部服务"
  ],
  "constraints": [
    "local_first",
    "privacy_safe"
  ],
  "non_goals": [
    "不证明密码绝对安全",
    "默认不查询在线泄露 API"
  ],
  "expanded_requirements": [
    {
      "id": "req-0001",
      "priority": "must",
      "description": "提供密码强度评分",
      "source": "inferred",
      "acceptance": ["输入密码后显示强度等级和主要原因"]
    }
  ],
  "target_outputs": ["local_web_app", "readme", "tests"],
  "definition_of_done": [
    "可以本地运行",
    "可以输入密码并获得强度反馈",
    "有隐私说明",
    "有基础测试"
  ],
  "verification_strategy": ["unit_tests", "smoke_test"],
  "budget": {
    "max_iterations": 8,
    "max_model_calls": 60
  }
}
```

枚举：

```text
goal_type:
  software_tool
  codebase_improvement
  research
  report
  knowledge_base
  automation
  unknown

expanded_requirements.priority:
  must
  should
  could
  wont

expanded_requirements.source:
  user
  inferred
  research
  memory
  decision
```

## 8. Task

文件：

```text
.agent/tasks/backlog.json
.agent/runs/<run_id>/task_plan.json
```

用途：

记录可调度任务。

```json
{
  "schema_version": "0.1.0",
  "task_id": "task-0001",
  "title": "实现密码强度评分",
  "description": "根据长度、字符多样性和常见弱密码规则给出评分",
  "status": "ready",
  "priority": "high",
  "role": "CoderAgent",
  "depends_on": [],
  "acceptance": [
    "输入密码后返回分数",
    "返回可解释原因",
    "包含单元测试"
  ],
  "allowed_tools": ["read_file", "search_code", "apply_patch", "run_tests"],
  "expected_artifacts": ["src/scoring.ts", "tests/scoring.test.ts"],
  "assigned_agent_id": null,
  "created_at": "2026-04-27T14:30:00+08:00",
  "updated_at": "2026-04-27T14:30:00+08:00",
  "notes": ""
}
```

枚举：

```text
task.status:
  backlog
  ready
  in_progress
  testing
  reviewing
  blocked
  done
  discarded

task.priority:
  critical
  high
  medium
  low
```

## 9. AgentSpec

用途：

定义智能体角色和权限。

```json
{
  "schema_version": "0.1.0",
  "agent_id": "agent-0001",
  "role": "CoderAgent",
  "model_tier": "medium",
  "allowed_tools": ["read_file", "search_code", "apply_patch", "run_tests"],
  "write_scope": "assigned_workspace",
  "budget": {
    "max_model_calls": 10,
    "max_tool_calls": 40
  },
  "instructions_ref": "AGENTS.md#coderagent"
}
```

枚举：

```text
agent.role:
  GoalSpecAgent
  PlannerAgent
  ArchitectAgent
  ProductAgent
  ResearchAgent
  CoderAgent
  UIExperienceAgent
  TesterAgent
  ReviewerAgent
  AutoCorrectionAgent
  MemoryAgent
  ReleaseAgent

model_tier:
  cheap
  medium
  strong
```

## 10. DecisionPoint

文件：

```text
.agent/runs/<run_id>/decisions.jsonl
```

用途：

记录需要用户操盘的重大分支。

```json
{
  "schema_version": "0.1.0",
  "decision_id": "decision-0001",
  "status": "pending",
  "question": "密码测试工具是否应该包含在线泄露查询？",
  "recommended_option_id": "local_optional_import",
  "options": [
    {
      "option_id": "no_breach_check",
      "label": "不做泄露检查",
      "tradeoff": "完全本地且简单，但现实风险提示较弱",
      "action": "cancel_scope"
    },
    {
      "option_id": "local_optional_import",
      "label": "本地可选导入",
      "tradeoff": "隐私安全，但需要用户准备本地列表",
      "action": "create_task"
    },
    {
      "option_id": "online_api",
      "label": "在线 API",
      "tradeoff": "方便，但有隐私和网络依赖问题",
      "action": "create_task"
    }
  ],
  "default_option_id": "local_optional_import",
  "impact": {
    "scope": "medium",
    "budget": "medium",
    "risk": "high",
    "quality": "medium"
  },
  "selected_option_id": null,
  "created_at": "2026-04-27T14:30:00+08:00",
  "resolved_at": null
}
```

枚举：

```text
decision.status:
  pending
  resolved
  defaulted
  cancelled

impact value:
  low
  medium
  high

decision.options[].action:
  create_task
  record_constraint
  cancel_scope
  require_replan
```

## 11. ContextSnapshot

文件：

```text
.agent/context/root_snapshot.json
.agent/context/snapshots/<timestamp>.json
```

用途：

压缩上下文，支持长任务续航。

```json
{
  "schema_version": "0.1.0",
  "snapshot_id": "snapshot-0001",
  "run_id": "run-20260427-0001",
  "created_at": "2026-04-27T14:30:00+08:00",
  "focus": "handoff for ReviewerAgent",
  "goal_summary": "构建本地优先密码测试工具",
  "definition_of_done": ["本地运行", "强度评分", "隐私说明", "测试通过"],
  "accepted_decisions": ["默认不使用在线泄露 API"],
  "active_tasks": ["task-0001", "task-0003"],
  "modified_files": [
    {
      "path": "src/scoring.ts",
      "reason": "实现强度评分"
    }
  ],
  "verification": [
    {
      "command": "npm test",
      "status": "passed",
      "summary": "12 tests passed"
    }
  ],
  "failures": [],
  "research_claims": [
    "密码强度评分不能等同于是否已经泄露"
  ],
  "open_risks": ["缺少 UI screenshot 检查"],
  "next_actions": ["运行 smoke test", "补 README"]
}
```

## 12. CommandRun

用途：

记录一次命令执行。

```json
{
  "schema_version": "0.1.0",
  "command_run_id": "cmd-0001",
  "run_id": "run-20260427-0001",
  "command": "plan",
  "args": {
    "goal": "做一个密码测试工具"
  },
  "status": "completed",
  "started_at": "2026-04-27T14:30:00+08:00",
  "ended_at": "2026-04-27T14:31:00+08:00",
  "artifacts": ["goal_spec.json", "task_plan.json"],
  "cost": {
    "model_calls": 3,
    "tool_calls": 8
  },
  "summary": "生成目标规格和 7 个任务"
}
```

枚举：

```text
command:
  init
  plan
  brainstorm
  research
  compact
  decide
  review
  debug
  handoff
  run

command.status:
  queued
  running
  completed
  failed
  blocked
  cancelled
```

## 13. ToolCall

文件：

```text
.agent/runs/<run_id>/tool_calls.jsonl
```

用途：

记录工具调用，支持审计和轨迹评估。

```json
{
  "schema_version": "0.1.0",
  "tool_call_id": "toolcall-0001",
  "run_id": "run-20260427-0001",
  "task_id": "task-0001",
  "agent_id": "agent-0001",
  "tool_name": "run_tests",
  "input_summary": "npm test",
  "output_summary": "12 tests passed",
  "status": "success",
  "started_at": "2026-04-27T14:30:00+08:00",
  "ended_at": "2026-04-27T14:30:10+08:00",
  "error": null
}
```

枚举：

```text
tool_call.status:
  success
  failure
  denied
  timeout
```

## 14. ModelCall

文件：

```text
.agent/runs/<run_id>/model_calls.jsonl
```

用途：

记录模型调用和成本。

```json
{
  "schema_version": "0.1.0",
  "model_call_id": "modelcall-0001",
  "run_id": "run-20260427-0001",
  "agent_id": "agent-0001",
  "purpose": "planning",
  "model_provider": "zhipu",
  "model_name": "glm-example",
  "model_tier": "strong",
  "input_tokens": 5000,
  "output_tokens": 1200,
  "status": "success",
  "created_at": "2026-04-27T14:30:00+08:00",
  "summary": "生成任务计划"
}
```

枚举：

```text
model_call.purpose:
  goal_spec
  planning
  brainstorming
  research
  coding
  review
  debugging
  summarization
  evaluation
```

## 15. Artifact

文件：

```text
.agent/runs/<run_id>/artifacts.jsonl
```

用途：

记录运行产物。

```json
{
  "schema_version": "0.1.0",
  "artifact_id": "artifact-0001",
  "run_id": "run-20260427-0001",
  "task_id": "task-0001",
  "type": "source_file",
  "path": "src/scoring.ts",
  "created_by": "agent-0001",
  "summary": "实现密码评分逻辑",
  "created_at": "2026-04-27T14:30:00+08:00"
}
```

枚举：

```text
artifact.type:
  source_file
  test_file
  report
  screenshot
  patch
  research_note
  eval_result
  context_snapshot
  memory_entry
```

## 16. Experiment

文件：

```text
.agent/runs/<run_id>/experiments.jsonl
```

用途：

记录 keep/discard 尝试。

```json
{
  "schema_version": "0.1.0",
  "experiment_id": "exp-0001",
  "run_id": "run-20260427-0001",
  "task_id": "task-0001",
  "idea": "增加常见弱密码检测",
  "baseline": {
    "tests_passed": 10,
    "requirement_coverage": 0.55
  },
  "candidate": {
    "changed_files": ["src/scoring.ts", "tests/scoring.test.ts"]
  },
  "evaluator": {
    "commands": ["npm test"],
    "metrics": ["tests_passed", "requirement_coverage"]
  },
  "metrics_after": {
    "tests_passed": 12,
    "requirement_coverage": 0.7
  },
  "decision": "keep",
  "reason": "覆盖率提升且测试通过"
}
```

枚举：

```text
experiment.decision:
  keep
  discard
  retry
  blocked
```

## 17. EvalReport

文件：

```text
.agent/runs/<run_id>/eval_report.json
```

用途：

记录验收评估。

```json
{
  "schema_version": "0.1.0",
  "run_id": "run-20260427-0001",
  "goal_eval": {
    "goal_clarity_score": 0.85,
    "requirement_expansion_score": 0.8,
    "definition_of_done_score": 0.82
  },
  "artifact_eval": {
    "required_artifacts_present": true
  },
  "outcome_eval": {
    "requirement_coverage": 0.75,
    "verification_pass_rate": 0.9,
    "documentation_score": 0.7
  },
  "trajectory_eval": {
    "scope_drift_score": 0.1,
    "cost_efficiency_score": 0.85
  },
  "cost_eval": {
    "within_budget": true
  },
  "overall": {
    "status": "pass",
    "score": 0.82,
    "reason": "核心需求覆盖，成本在预算内"
  }
}
```

枚举：

```text
overall.status:
  pass
  partial
  fail
```

## 18. CostReport

文件：

```text
.agent/runs/<run_id>/cost_report.json
```

用途：

记录成本和预算状态。

```json
{
  "schema_version": "0.1.0",
  "run_id": "run-20260427-0001",
  "model_calls": 34,
  "tool_calls": 82,
  "estimated_input_tokens": 120000,
  "estimated_output_tokens": 18000,
  "strong_model_calls": 8,
  "cheap_model_calls": 12,
  "repair_attempts": 2,
  "context_compactions": 1,
  "user_decisions": 2,
  "status": "within_budget",
  "warnings": []
}
```

枚举：

```text
cost.status:
  within_budget
  near_limit
  exceeded
  stopped
```

## 19. MemoryEntry

文件：

```text
.agent/memory/*.jsonl
```

用途：

记录可复用记忆。

```json
{
  "schema_version": "0.1.0",
  "memory_id": "memory-0001",
  "type": "project_decision",
  "content": "用户偏好本地优先，不默认调用在线泄露 API",
  "source": {
    "run_id": "run-20260427-0001",
    "decision_id": "decision-0001"
  },
  "tags": ["privacy", "local_first"],
  "confidence": 0.9,
  "created_at": "2026-04-27T14:30:00+08:00"
}
```

枚举：

```text
memory.type:
  user_preference
  project_decision
  architecture_note
  research_claim
  experiment_lesson
  tool_knowledge
  failure_lesson
```

## 20. Event

文件：

```text
.agent/runs/<run_id>/events.jsonl
```

用途：

记录系统事件。

```json
{
  "schema_version": "0.1.0",
  "event_id": "event-0001",
  "run_id": "run-20260427-0001",
  "timestamp": "2026-04-27T14:30:00+08:00",
  "type": "phase_changed",
  "actor": "orchestrator",
  "summary": "PLAN -> IMPLEMENT",
  "data": {
    "from": "PLAN",
    "to": "IMPLEMENT"
  }
}
```

枚举：

```text
event.type:
  run_started
  run_completed
  phase_changed
  task_created
  task_updated
  tool_called
  model_called
  decision_created
  decision_resolved
  artifact_created
  verification_run
  repair_attempted
  context_compacted
  budget_warning
  policy_denied
  error
```

## 21. HandoffPackage

文件：

```text
.agent/context/handoffs/<timestamp>.json
```

用途：

给另一个智能体或未来运行续接。

```json
{
  "schema_version": "0.1.0",
  "handoff_id": "handoff-0001",
  "from_agent_id": "agent-0001",
  "to_role": "ReviewerAgent",
  "snapshot_id": "snapshot-0001",
  "current_task_ids": ["task-0003"],
  "recent_artifacts": ["artifact-0003", "artifact-0004"],
  "known_risks": ["缺少移动端检查"],
  "recommended_next_command": "review",
  "created_at": "2026-04-27T14:30:00+08:00"
}
```

## 22. 状态转移约束

### 22.1 Task 状态转移

```text
backlog -> ready
ready -> in_progress
in_progress -> testing
testing -> reviewing
reviewing -> done
in_progress -> blocked
testing -> blocked
reviewing -> blocked
blocked -> ready
in_progress -> discarded
```

禁止：

- `done -> in_progress`，除非创建新任务。
- `discarded -> done`，除非恢复为新任务。

### 22.2 Run 状态转移

```text
queued -> running
running -> paused
paused -> running
running -> blocked
blocked -> running
running -> completed
running -> failed
running -> cancelled
```

## 23. 最小实现优先级

MVP 必须先实现以下对象：

1. `ProjectConfig`
2. `PolicyConfig`
3. `Run`
4. `GoalSpec`
5. `Task`
6. `DecisionPoint`
7. `ContextSnapshot`
8. `ToolCall`
9. `ModelCall`
10. `Artifact`
11. `EvalReport`
12. `CostReport`
13. `Event`

其余对象可以在 V1 中补齐。

## 24. Schema 校验策略

实现时应提供：

- JSON Schema 文件。
- 读入时校验。
- 写出前校验。
- 版本迁移函数。
- 默认值填充。
- 清晰错误消息。

推荐目录：

```text
schemas/
  project_config.schema.json
  policy_config.schema.json
  run.schema.json
  goal_spec.schema.json
  task.schema.json
  decision_point.schema.json
  context_snapshot.schema.json
  tool_call.schema.json
  model_call.schema.json
  artifact.schema.json
  eval_report.schema.json
  cost_report.schema.json
  event.schema.json
```
