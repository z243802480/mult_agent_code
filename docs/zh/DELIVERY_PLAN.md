# 多智能体自主开发系统 - 交付计划

## 1. 文档目的

本文档定义 MVP 范围、阶段路线图、需求保留策略和实施任务。

原则：

- 可以分阶段实现。
- 不能因为 MVP 收窄就删除有价值需求。
- 暂缓需求必须进入路线图、风险处理或后续任务池。
- 高风险能力必须在设计层给出控制机制。
- 成本控制是系统能力的一部分。

## 2. MVP 定位

MVP 的目标是验证最关键的 agent harness 闭环：

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

## 3. MVP 必做能力

必须包含：

- CLI 入口。
- `/init` 初始化。
- 目标规格化。
- 基础需求扩展。
- 任务看板。
- 单工作区执行。
- 工具注册表。
- 基础自动纠错。
- `/compact`。
- 最终报告。
- 成本报告。
- 安全策略。

MVP 可以暂缓：

- 多智能体并发。
- Git worktree 合并队列。
- 完整 Web dashboard。
- 完整论文调研和引用系统。
- 高级向量记忆。
- PDF 生成。
- UI screenshot 自动检查。
- 插件市场。
- 分布式实验执行。

## 4. 阶段路线图

### Phase 0：文档和规格冻结

产物：

- `PRODUCT_SPEC.md`
- `ARCHITECTURE.md`
- `DATA_MODEL.md`
- `RUNTIME_COMMANDS.md`
- `DELIVERY_PLAN.md`
- `QUALITY_AND_EVALUATION.md`
- `COST_SECURITY_RISK.md`

### Phase 1：单 agent harness

目标：

- 实现最小运行时。
- 支持 `/init`、`/plan`、`/compact`。
- 支持单 CoderAgent。
- 支持工具调用日志。

### Phase 2：验证和自动修复

目标：

- 接入测试命令。
- 接入失败分析。
- 接入最小修复循环。
- 接入 keep/discard。

### Phase 3：需求扩展和决策管理

目标：

- 接入 `/brainstorm`。
- 支持模糊目标需求扩展。
- 支持 `DecisionPoint`。
- 支持决策颗粒度配置。

### Phase 4：Research 和 UI/Experience

目标：

- 接入基础调研工作流。
- 接入 UI/Experience 输出判断。
- 支持 Web/CLI/报告等输出形态建议。

### Phase 5：多 agent 和工作区隔离

目标：

- 支持多个 agent 并行。
- 支持 Git worktree。
- 支持评审和合并队列。

## 5. MVP 默认策略

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

## 6. 实施任务清单

### 6.1 阶段 0：工程准备

#### T-0001 初始化 Python 项目骨架

产物：

- `pyproject.toml`
- `src/agent_runtime/__init__.py`
- `tests/`

验收：

- `pytest` 可运行。
- 包可以被导入。

#### T-0002 创建基础目录结构

产物：

- `src/agent_runtime/commands/`
- `src/agent_runtime/core/`
- `src/agent_runtime/tools/`
- `src/agent_runtime/models/`
- `src/agent_runtime/storage/`
- `src/agent_runtime/evaluation/`
- `src/agent_runtime/security/`

### 6.2 阶段 1：Schema 和存储

#### T-0101 创建核心 JSON Schema

产物：

- `schemas/*.schema.json`

验收：

- 每个 schema 能加载。
- 示例数据能通过校验。
- 缺失必填字段时校验失败。

#### T-0102 实现 SchemaValidator

产物：

- `src/agent_runtime/storage/schema_validator.py`
- 单元测试。

#### T-0103 实现 JSON/JSONL 存储

产物：

- `json_store.py`
- `jsonl_store.py`
- 单元测试。

### 6.3 阶段 2：初始化和配置

#### T-0201 实现 ProjectStore

验收：

- 能创建 `.agent/` 目录。
- 能读写 `project.json`。
- 能读写 `policies.json`。
- 重复运行不破坏已有文件。

#### T-0202 实现 `/init`

验收：

- 空目录可初始化。
- 已有目录可初始化。
- 重复运行安全。
- 不覆盖用户手写 `AGENTS.md`。

#### T-0203 实现 CLI 基础入口

验收：

- 本地可执行 `agent init`。
- 初始化后目录结构正确。

### 6.4 阶段 3：事件、成本和任务看板

任务：

- T-0301 实现 RunStore。
- T-0302 实现 EventLogger。
- T-0303 实现 BudgetController。
- T-0304 实现 TaskBoard。

验收：

- run 目录可创建。
- 事件可写入 JSONL。
- 超预算能阻止继续。
- 任务状态转移受控。

### 6.5 阶段 4：模型适配和 GoalSpec

任务：

- T-0401 实现 ModelClient 抽象。
- T-0402 实现 GoalSpecAgent。
- T-0403 实现 `/plan`。

验收：

- 支持 OpenAI-compatible chat 调用。
- 对“做一个密码测试工具”生成结构化 GoalSpec。
- 生成任务计划。

### 6.6 阶段 5：工具层和受控执行

任务：

- T-0501 实现文件和搜索工具。
- T-0502 实现补丁工具。
- T-0503 实现命令和测试工具。

验收：

- 可读取允许路径。
- 禁止读取受保护路径。
- 安全 shell 可执行。
- 危险 shell 被拒绝。

### 6.7 阶段 6：执行闭环

任务：

- T-0601 实现 CoderAgent。
- T-0602 实现 EvalRunner。
- T-0603 实现 AutoCorrectionAgent。
- T-0604 实现 ReviewerAgent。

验收：

- 能根据任务修改文件。
- 能运行验证命令。
- 失败时能尝试修复。
- keep/discard 前有评审。

### 6.8 阶段 7：上下文和报告

任务：

- T-0701 实现 `/compact`。
- T-0702 实现 ReporterAgent。
- T-0703 实现 `agent run`。

验收：

- 生成 ContextSnapshot。
- 生成 final_report。
- 输入目标后能跑通最小闭环。

### 6.9 阶段 8：MVP 验收场景

任务：

- T-0801 创建 password_tool benchmark。
- T-0802 创建 failing_tests benchmark。
- T-0803 创建 compact handoff benchmark。

## 7. MVP 完成定义

MVP 完成必须满足：

- `/init` 可用。
- `/plan` 可用。
- `agent run` 可跑通最小闭环。
- `/compact` 可用。
- 至少 2 个 benchmark 通过。
- 成本报告可生成。
- 安全策略能阻止危险命令。
- 最终报告可生成。

## 8. 需求保留策略

每个需求都应处于以下状态之一：

- `mvp`
- `v1`
- `v2`
- `v3`
- `research`
- `blocked`

不能使用“删除”作为默认处理方式。

如果需求风险过高，应转化为：

- 权限控制。
- 预算限制。
- 人类决策点。
- 沙箱隔离。
- 验证门禁。
- 灰度启用。
