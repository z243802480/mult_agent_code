# 多智能体自主开发系统 - MVP 实施任务清单

## 1. 文档目的

本文档将 MVP 拆成可执行工程任务。

任务按照阶段组织，每个任务包含：

- 目标。
- 产物。
- 验收条件。
- 依赖。

## 2. 阶段 0：工程准备

### T-0001 初始化 Python 项目骨架

目标：

创建基础 Python 工程。

产物：

- `pyproject.toml`
- `src/agent_runtime/__init__.py`
- `tests/`

验收：

- `pytest` 可运行。
- 包可以被导入。
- README 说明基本运行方式。

依赖：

- 无。

### T-0002 创建基础目录结构

目标：

创建运行时模块目录。

产物：

- `src/agent_runtime/commands/`
- `src/agent_runtime/core/`
- `src/agent_runtime/tools/`
- `src/agent_runtime/models/`
- `src/agent_runtime/storage/`
- `src/agent_runtime/evaluation/`
- `src/agent_runtime/security/`

验收：

- 每个目录有 `__init__.py`。
- 目录结构符合 `TECHNICAL_PLAN.md`。

依赖：

- T-0001。

## 3. 阶段 1：Schema 和存储

### T-0101 创建核心 JSON Schema

目标：

为 MVP 核心对象创建 schema。

产物：

- `schemas/project_config.schema.json`
- `schemas/policy_config.schema.json`
- `schemas/run.schema.json`
- `schemas/goal_spec.schema.json`
- `schemas/task.schema.json`
- `schemas/decision_point.schema.json`
- `schemas/context_snapshot.schema.json`
- `schemas/tool_call.schema.json`
- `schemas/model_call.schema.json`
- `schemas/artifact.schema.json`
- `schemas/eval_report.schema.json`
- `schemas/cost_report.schema.json`
- `schemas/event.schema.json`

验收：

- 每个 schema 能加载。
- 示例数据能通过校验。
- 缺失必填字段时校验失败。

依赖：

- T-0002。

### T-0102 实现 SchemaValidator

目标：

实现统一 schema 校验器。

产物：

- `src/agent_runtime/storage/schema_validator.py`
- 单元测试。

验收：

- 能按对象类型校验 JSON。
- 校验失败返回清晰错误。

依赖：

- T-0101。

### T-0103 实现 JSON/JSONL 存储

目标：

实现读写 JSON 和 JSONL 的基础能力。

产物：

- `json_store.py`
- `jsonl_store.py`
- 单元测试。

验收：

- 可写入和读取 JSON。
- 可 append JSONL。
- 可读取 JSONL 列表。
- 写入前可选 schema 校验。

依赖：

- T-0102。

## 4. 阶段 2：初始化和配置

### T-0201 实现 ProjectStore

目标：

管理 `.agent/` 项目文件。

产物：

- `project_store.py`
- 单元测试。

验收：

- 能创建 `.agent/` 目录。
- 能读写 `project.json`。
- 能读写 `policies.json`。
- 重复运行不破坏已有文件。

依赖：

- T-0103。

### T-0202 实现 `/init`

目标：

实现初始化命令。

产物：

- `commands/init_command.py`
- `AGENTS.md` 模板。
- `.agent/project.json`
- `.agent/policies.json`
- `.agent/context/root_snapshot.json`

验收：

- 空目录可初始化。
- 已有目录可初始化。
- 重复运行安全。
- 不覆盖用户手写 `AGENTS.md`。

依赖：

- T-0201。

### T-0203 实现 CLI 基础入口

目标：

提供命令行入口。

产物：

- `cli.py`
- `agent init`

验收：

- 本地可执行 `agent init`。
- 初始化后目录结构正确。

依赖：

- T-0202。

## 5. 阶段 3：事件、成本和任务看板

### T-0301 实现 RunStore

目标：

创建和管理 run 目录。

产物：

- `run_store.py`
- 单元测试。

验收：

- 能创建 run id。
- 能创建 run 目录。
- 能写入 `run.json`。

依赖：

- T-0103。

### T-0302 实现 EventLogger

目标：

记录事件日志。

产物：

- `event_logger.py`
- `events.jsonl`

验收：

- 能记录 phase_changed、task_created、tool_called 等事件。
- 每条事件符合 schema。

依赖：

- T-0301。

### T-0303 实现 BudgetController

目标：

控制模型调用、工具调用和修复次数。

产物：

- `budget.py`
- 单元测试。

验收：

- 超过预算时阻止继续。
- 接近预算时给出 warning。
- 能生成成本摘要。

依赖：

- T-0201。

### T-0304 实现 TaskBoard

目标：

管理任务状态。

产物：

- `task_board.py`
- 单元测试。

验收：

- 能创建任务。
- 能更新状态。
- 不允许非法状态转移。
- 能查询 ready 任务。

依赖：

- T-0101。

## 6. 阶段 4：模型适配和 GoalSpec

### T-0401 实现 ModelClient 抽象

目标：

定义模型调用接口。

产物：

- `models/base.py`
- `models/openai_compatible.py`

验收：

- 支持 chat 调用。
- 支持超时。
- 支持失败重试。
- 记录 ModelCall。

依赖：

- T-0302。

### T-0402 实现 GoalSpecAgent

目标：

把自然语言目标转成 GoalSpec。

产物：

- `agents/goal_spec_agent.py`
- prompt 模板。
- 单元或集成测试。

验收：

- 对“做一个密码测试工具”生成结构化 GoalSpec。
- 包含扩展需求、非目标、完成定义和验证策略。

依赖：

- T-0401。

### T-0403 实现 `/plan`

目标：

生成 GoalSpec 和任务计划。

产物：

- `commands/plan_command.py`
- `PlannerAgent`

验收：

- 生成 `goal_spec.json`。
- 生成 `task_plan.json`。
- 任务符合 `TASK_DECOMPOSITION_GUIDE.md`。

依赖：

- T-0402、T-0304。

## 7. 阶段 5：工具层和受控执行

### T-0501 实现文件和搜索工具

目标：

提供基础文件读取和搜索。

产物：

- `file_tools.py`
- `search_tools.py`

验收：

- 可读取允许路径。
- 禁止读取受保护路径。
- 搜索返回结构化结果。

依赖：

- T-0201。

### T-0502 实现补丁工具

目标：

支持受控修改文件。

产物：

- `patch_tools.py`

验收：

- 可应用 patch。
- 应用前检查路径权限。
- 失败时返回清晰错误。

依赖：

- T-0501。

### T-0503 实现命令和测试工具

目标：

运行 shell 命令和测试命令。

产物：

- `command_tools.py`
- `test_tools.py`
- `shell_guard.py`

验收：

- 允许安全命令。
- 阻止危险命令。
- 记录 ToolCall。

依赖：

- T-0302。

## 8. 阶段 6：执行闭环

### T-0601 实现 CoderAgent

目标：

根据任务修改文件。

产物：

- `coder_agent.py`

验收：

- 能读取任务和上下文。
- 能生成 patch。
- 能调用文件工具。

依赖：

- T-0502、T-0401。

### T-0602 实现 EvalRunner

目标：

执行验证命令并生成结果。

产物：

- `eval_runner.py`

验收：

- 能运行测试命令。
- 能解析成功/失败。
- 能写入 eval report。

依赖：

- T-0503。

### T-0603 实现 AutoCorrectionAgent

目标：

失败时生成修复尝试。

产物：

- `auto_correction_agent.py`

验收：

- 能总结失败。
- 能尝试最小修复。
- 超过次数后停止。

依赖：

- T-0601、T-0602。

### T-0604 实现 ReviewerAgent

目标：

评审改动和需求覆盖。

产物：

- `reviewer_agent.py`
- `review_report.md`

验收：

- 能指出缺失测试、范围膨胀、安全风险。
- 能给出 keep/discard 建议。

依赖：

- T-0602。

## 9. 阶段 7：上下文和报告

### T-0701 实现 `/compact`

目标：

生成 ContextSnapshot。

产物：

- `compact_command.py`
- `context_manager.py`

验收：

- 保留目标、任务、决策、验证、失败、下一步。
- 可写入 `.agent/context/snapshots/`。

依赖：

- T-0301、T-0304。

### T-0702 实现 ReporterAgent

目标：

生成最终报告。

产物：

- `reporter_agent.py`
- `final_report.md`

验收：

- 报告包含目标、扩展需求、任务、改动、验证、成本、风险和下一步。

依赖：

- T-0701。

### T-0703 实现 `agent run`

目标：

串联最小闭环。

产物：

- `run_command.py`
- Orchestrator MVP。

验收：

- 输入目标后能完成 plan、task、执行、验证、报告。
- 失败时能进入 debug/repair。
- 成本报告可生成。

依赖：

- T-0403、T-0601、T-0602、T-0702。

## 10. 阶段 8：MVP 验收场景

### T-0801 创建 password_tool benchmark

目标：

测试模糊目标扩展和最小实现。

产物：

- `benchmarks/password_tool/`

验收：

- 输入目标能生成合理需求。
- 至少生成任务计划和报告。

依赖：

- T-0703。

### T-0802 创建 failing_tests benchmark

目标：

测试自动修复。

产物：

- `benchmarks/failing_tests_project/`

验收：

- 系统能捕获失败。
- 能尝试修复。
- 能报告成功或失败。

依赖：

- T-0603。

### T-0803 创建 compact handoff benchmark

目标：

测试长任务上下文压缩。

产物：

- `benchmarks/long_context_project/`

验收：

- `/compact` 后能继续任务。

依赖：

- T-0701。

## 11. MVP 完成定义

MVP 完成必须满足：

- `/init` 可用。
- `/plan` 可用。
- `agent run` 可跑通最小闭环。
- `/compact` 可用。
- 至少 2 个 benchmark 通过。
- 成本报告可生成。
- 安全策略能阻止危险命令。
- 最终报告可生成。

## 12. 后续 V1 任务池

MVP 后再做：

- `/brainstorm` 完整实现。
- `/research` 联网调研。
- `DecisionManager` 完整交互。
- Git worktree。
- 多 agent 并发。
- UIExperienceAgent。
- Web dashboard。
- SQLite 存储。
- PDF 报告。
