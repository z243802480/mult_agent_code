# 多智能体自主开发系统 - 架构与技术方案

## 1. 架构原则

系统围绕 agent runtime 组织。智能体是可替换工作者，运行时是稳定控制平面。

核心原则：

- Runtime first, agents second。
- 稳定根上下文。
- 显式状态。
- 窄工具。
- 权限边界。
- 阶段门禁。
- 可恢复路径。
- 成本预算。
- 用户操盘。
- 根文件纪律。

## 2. 运行时组件架构

```text
CLI / 本地 UI
  -> 命令路由器
       -> /init
       -> /plan
       -> /brainstorm
       -> /research
       -> /compact
       -> /decide
       -> /review
       -> /debug
       -> /handoff
  -> 编排器
       -> 状态机
       -> 任务调度器
       -> 决策管理器
       -> 预算控制器
  -> 上下文层
       -> 根指导加载器
       -> 上下文检索器
       -> 上下文压缩器
       -> 交接包构建器
  -> 智能体层
       -> PlannerAgent
       -> ResearchAgent
       -> CoderAgent
       -> UIExperienceAgent
       -> TesterAgent
       -> ReviewerAgent
       -> AutoCorrectionAgent
  -> 工具层
       -> 文件工具
       -> 搜索工具
       -> 补丁工具
       -> Shell/测试工具
       -> 浏览器/截图工具
       -> 调研工具
       -> 记忆工具
  -> 持久化层
       -> AGENTS.md
       -> .agent/project.json
       -> .agent/policies.json
       -> .agent/context/
       -> .agent/tasks/
       -> .agent/runs/
       -> .agent/memory/
       -> Git / Worktrees
```

编排器不负责“变聪明”，而是负责状态、权限、任务、预算和产物流转。判断和生成由专门智能体在运行时控制下完成。

## 3. 核心数据流

```text
用户目标或命令
  -> 命令路由器
  -> 根指导和记忆检索
  -> 编排器状态转换
  -> 智能体提示词组装
  -> 工具调用和产物创建
  -> 验证和评审
  -> 保留/丢弃决策
  -> 上下文快照和记忆更新
  -> 用户报告或下一个决策点
```

对于长任务，连续性的来源应该是稳定产物，而不是临时聊天历史。

## 4. 主运行循环

```text
1. 接收用户目标。
2. 生成 GoalSpec。
3. 构建初始任务计划。
4. 选择输出策略。
5. 检测重大决策点。
6. 在需要时压缩上下文。
7. 准备工作区。
8. 分配就绪任务。
9. 智能体使用允许工具执行工作。
10. 运行时记录产物和事件。
11. 运行验证。
12. 通过则评审并保留。
13. 失败则触发自动纠错。
14. 修复失败则回滚或标记阻塞。
15. 更新记忆。
16. 持续运行，直到完成、预算耗尽或阻塞。
17. 生成最终报告。
```

## 5. 状态机

```text
INIT
  -> SPEC
  -> PLAN
  -> BRAINSTORM 可选
  -> DECIDE 可选
  -> RESEARCH 可选
  -> DESIGN
  -> IMPLEMENT
  -> VERIFY
  -> REVIEW
  -> REPAIR 可选
  -> KEEP_OR_DISCARD
  -> MEMORY_UPDATE
  -> REPORT
  -> DONE
```

## 6. 技术栈

第一版推荐 Python 实现运行时。

```text
语言：Python 3.11+
CLI：Typer
配置：Pydantic / pydantic-settings
Schema 校验：Pydantic model + JSON Schema 导出，或 jsonschema
存储：文件系统 + JSONL，后续补 SQLite
日志：标准 logging + JSONL，后续可加 structlog
测试：pytest
模型接口：OpenAI-compatible adapter
异步：第一版同步优先，后续引入 asyncio
```

理由：

- 主流、轻量、自主可控。
- 适合编排、文件处理、自动化和测试。
- 不被 LangChain/LangGraph 等重框架绑死。
- JSONL 和文件系统便于审计和调试。
- 后续可平滑迁移 SQLite、Web dashboard 和多 agent 并发。

## 7. 项目目录结构

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

## 8. 模块边界

### 8.1 CLI 层

职责：

- 解析用户命令。
- 调用 Command Router。
- 输出人类可读摘要。

### 8.2 Command Router

职责：

- 将命令映射到工作流。
- 检查权限和预算。
- 加载上下文。
- 写入命令执行记录。

### 8.3 Core Runtime

职责：

- Orchestrator。
- State Machine。
- Task Scheduler。
- Decision Manager。
- Budget Controller。
- Context Manager。

### 8.4 Storage 层

职责：

- 读写 `.agent/`。
- JSON/JSONL 持久化。
- schema 校验。
- run 目录管理。

### 8.5 Tools 层

职责：

- 提供结构化工具。
- 包装文件、搜索、补丁、命令和测试能力。
- 记录 ToolCall。
- 执行权限检查。

### 8.6 Model Provider 层

职责：

- 抽象模型调用。
- 支持 OpenAI-compatible API。
- 记录 ModelCall。
- 支持超时、重试、模型路由和成本估算。

### 8.7 Agents 层

职责：

- 定义角色化 agent。
- 从上下文和任务构造 prompt。
- 调用模型和工具。

### 8.8 Evaluation 层

职责：

- 运行验证命令。
- 计算 eval report。
- 评估 outcome、trajectory、cost。

### 8.9 Security 层

职责：

- 路径保护。
- shell 命令分级。
- 高风险操作拦截。
- secrets 检测。

## 9. 统一日志与模块通讯

运行时内部模块之间应通过明确对象通讯，而不是散传无结构字典。

核心通讯对象：

- `RuntimeContext`：携带 root、run_id、policy、schema validator、event logger、budget controller。
- `ToolResult`：所有工具统一返回 `ok`、`summary`、`data`、`warnings`、`error`、`status`。
- `ToolRegistry`：所有工具调用统一入口。

日志原则：

- 工具调用必须写入 `tool_calls.jsonl`。
- 关键运行事件必须写入 `events.jsonl`。
- 模型调用必须写入 `model_calls.jsonl`。
- 成本信息必须进入 `cost_report.json`。
- 失败必须保留错误摘要，而不是只在控制台打印。

工具调用链路：

```text
Agent / Command
  -> ToolRegistry.call()
  -> BudgetController pre-check
  -> Tool.run()
  -> ToolResult
  -> tool_calls.jsonl
  -> events.jsonl
```

预算检查必须在工具执行前发生。权限检查必须在文件读取、文件写入、shell 执行等高风险操作前发生。

这种设计保证：

- 排查问题时能看到每次工具调用输入摘要、输出摘要、状态和错误。
- 超预算工具不会先执行后报错。
- 工具失败不会以异常形式散落到上层，而是转换为结构化结果。
- 后续 agent 层可以稳定依赖统一工具协议。

## 10. 工作区策略

MVP：

- 一个主工作区。
- 一个临时实现工作区或受控写入模式。
- 在保留/丢弃前检查 diff。

未来：

- 每个智能体一个 Git worktree。
- 合并队列。
- 冲突解决器。
- 容器隔离。

## 11. 推荐依赖

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

## 12. 实现门禁

进入下一阶段前必须满足：

- schema 校验通过。
- 单元测试通过。
- 至少一个端到端场景通过。
- 成本报告可生成。
- `final_report.md` 可生成。
- 高风险 shell 命令被拦截。

## 13. 后续扩展

- SQLite 存储。
- Git worktree。
- 多 agent 并发。
- Web dashboard。
- ResearchAgent 联网调研。
- UI screenshot 检查。
- 长期向量记忆。
