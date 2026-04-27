# 多智能体自主开发系统 - 技术实施方案

## 1. 文档目的

本文档将产品目标、需求文档和架构设计转化为第一版工程实现方案。

目标：

- 明确 MVP 技术栈。
- 明确目录结构。
- 明确核心模块边界。
- 明确实现顺序。
- 明确哪些能力先做真实实现，哪些先保留接口。

## 2. 第一版技术选择

推荐第一版使用 Python 实现运行时。

理由：

- 编排、文件处理、JSON schema、CLI、测试和自动化生态成熟。
- 容易和本地脚本、Git、测试命令、文档处理集成。
- 后续接 FastAPI dashboard 也自然。

推荐栈：

```text
语言：Python 3.11+
CLI：Typer
配置：Pydantic / pydantic-settings
Schema 校验：jsonschema 或 Pydantic model
存储：文件系统 + JSONL，后续补 SQLite
日志：structlog 或标准 logging + JSONL
测试：pytest
模型接口：OpenAI-compatible adapter
异步：第一版同步优先，后续引入 asyncio
```

## 3. 项目目录结构

推荐：

```text
mult_agent_code/
  docs/
    zh/
  schemas/
  src/
    agent_runtime/
      __init__.py
      cli.py
      config/
      core/
      commands/
      agents/
      tools/
      models/
      storage/
      evaluation/
      security/
      utils/
  tests/
    unit/
    integration/
    scenarios/
  benchmarks/
    password_tool/
    markdown_kb/
    file_renamer/
  pyproject.toml
  README.md
```

## 4. 模块边界

### 4.1 CLI 层

目录：

```text
src/agent_runtime/cli.py
```

职责：

- 解析用户命令。
- 调用 Command Router。
- 输出人类可读摘要。

MVP 命令：

- `init`
- `run`
- `plan`
- `compact`
- `review`

### 4.2 Command Router

目录：

```text
src/agent_runtime/commands/
```

职责：

- 将命令映射到工作流。
- 检查权限和预算。
- 加载上下文。
- 写入命令执行记录。

初始命令模块：

```text
init_command.py
plan_command.py
compact_command.py
review_command.py
run_command.py
```

### 4.3 Core Runtime

目录：

```text
src/agent_runtime/core/
```

职责：

- Orchestrator。
- State Machine。
- Task Scheduler。
- Decision Manager。
- Budget Controller。
- Context Manager。

初始文件：

```text
orchestrator.py
state_machine.py
task_board.py
decision_manager.py
budget.py
context_manager.py
```

### 4.4 Storage 层

目录：

```text
src/agent_runtime/storage/
```

职责：

- 读写 `.agent/`。
- JSON/JSONL 持久化。
- schema 校验。
- run 目录管理。

初始文件：

```text
project_store.py
run_store.py
jsonl_store.py
schema_validator.py
```

### 4.5 Tools 层

目录：

```text
src/agent_runtime/tools/
```

职责：

- 提供结构化工具。
- 包装文件、搜索、补丁、命令和测试能力。
- 记录 ToolCall。
- 执行权限检查。

初始工具：

```text
file_tools.py
search_tools.py
patch_tools.py
command_tools.py
test_tools.py
git_tools.py
```

### 4.6 Model Provider 层

目录：

```text
src/agent_runtime/models/
```

职责：

- 抽象模型调用。
- 支持 OpenAI-compatible API。
- 记录 ModelCall。
- 支持超时、重试、模型路由和成本估算。

初始文件：

```text
base.py
openai_compatible.py
router.py
usage.py
```

### 4.7 Agents 层

目录：

```text
src/agent_runtime/agents/
```

职责：

- 定义角色化 agent。
- 从上下文和任务构造 prompt。
- 调用模型和工具。

MVP agent：

```text
goal_spec_agent.py
planner_agent.py
coder_agent.py
reviewer_agent.py
auto_correction_agent.py
reporter_agent.py
```

### 4.8 Evaluation 层

目录：

```text
src/agent_runtime/evaluation/
```

职责：

- 运行验证命令。
- 计算 eval report。
- 评估 outcome、trajectory、cost。

初始文件：

```text
eval_runner.py
outcome_eval.py
trajectory_eval.py
cost_eval.py
```

### 4.9 Security 层

目录：

```text
src/agent_runtime/security/
```

职责：

- 路径保护。
- shell 命令分级。
- 高风险操作拦截。
- secrets 检测。

初始文件：

```text
policy.py
path_guard.py
shell_guard.py
secret_scanner.py
```

## 5. 核心运行链路

### 5.1 `/init`

```text
CLI
  -> InitCommand
  -> detect workspace
  -> create AGENTS.md
  -> create .agent/project.json
  -> create .agent/policies.json
  -> create root_snapshot.json
  -> create backlog.json
```

### 5.2 `run "<goal>"`

```text
CLI
  -> RunCommand
  -> create Run
  -> GoalSpecAgent
  -> PlannerAgent
  -> TaskBoard
  -> CoderAgent
  -> Tool calls
  -> EvalRunner
  -> AutoCorrectionAgent if failed
  -> ReviewerAgent
  -> ReporterAgent
```

### 5.3 `/compact`

```text
CLI or runtime policy
  -> CompactCommand
  -> load run state
  -> summarize critical context
  -> write ContextSnapshot
  -> update event log
```

## 6. MVP 实现策略

第一版避免过度工程化：

- 先用文件系统和 JSONL，不急着上数据库。
- 先用单工作区，不急着并发 worktree。
- 先实现 OpenAI-compatible 一个模型适配器。
- 先实现命令驱动，再实现后台调度。
- 先写 schema 和测试，再扩展复杂 agent。

## 7. 依赖建议

```toml
[project]
requires-python = ">=3.11"

dependencies = [
  "typer",
  "pydantic",
  "pydantic-settings",
  "jsonschema",
  "rich",
  "httpx",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-cov",
  "ruff",
  "mypy",
]
```

## 8. 配置来源

配置优先级：

```text
CLI 参数
  > 环境变量
  > .agent/policies.json
  > 默认配置
```

模型配置建议使用环境变量：

```text
AGENT_MODEL_BASE_URL
AGENT_MODEL_API_KEY
AGENT_MODEL_NAME
AGENT_MODEL_PROVIDER
```

## 9. 实现门禁

进入下一阶段前必须满足：

- schema 校验通过。
- 单元测试通过。
- 至少一个端到端场景通过。
- 成本报告可生成。
- final_report.md 可生成。
- 高风险 shell 命令被拦截。

## 10. 后续扩展点

MVP 之后扩展：

- SQLite 存储。
- Git worktree。
- 多 agent 并发。
- Web dashboard。
- ResearchAgent 联网调研。
- UI screenshot 检查。
- 长期向量记忆。
