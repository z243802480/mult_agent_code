# 多智能体自主开发系统 - 设计文档

## 1. 系统架构

系统围绕智能体运行时组织。智能体是可替换的工作者，运行时是稳定的控制平面。

```text
用户目标
  -> 目标输入
  -> 智能体运行时
       -> 上下文管理器
       -> 任务看板
       -> 工具注册表
       -> 命令注册表
       -> 权限管理器
       -> 决策管理器
       -> 工作区管理器
       -> 评估运行器
       -> 记忆存储
       -> 事件日志
       -> 预算控制器
       -> 恢复引擎
  -> 专门智能体
       -> 规划
       -> 架构
       -> 调研
       -> 编码
       -> UI/体验
       -> 测试
       -> 评审
       -> 自动纠错
       -> 记忆
       -> 发布
  -> 产物
       -> 代码
       -> 报告
       -> UI
       -> 测试
       -> 实验日志
       -> 最终总结
```

### 1.1 运行时组件架构

运行时由多个协作的控制平面模块组成。

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

编排器不应该把所有智能都塞进自己内部。它负责协调状态、权限、任务、预算和产物流转。专门智能体在运行时控制下提供判断和生成能力。

### 1.2 核心数据流

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

对于长任务，这条数据流会经历多轮迭代。连续性的来源应该是稳定产物，而不是临时聊天历史。

### 1.3 架构分层

系统应保持以下层次分离：

- 接口层：CLI、本地 UI 和未来仪表盘。
- 命令层：`/init`、`/brainstorm`、`/compact` 等可复用工作流。
- 编排层：状态机、任务调度、决策升级和预算控制。
- 智能体层：角色化模型工作者。
- 工具层：暴露给智能体的结构化能力。
- 评估层：测试、构建、评审、基准、截图检查和轨迹评估。
- 持久化层：根指导、项目元数据、事件日志、任务、记忆、上下文快照和 Git 状态。

这种分层能保持系统可扩展。新的智能体、工具、命令和 UI 表面应该能接入运行时，而不需要重写整个控制平面。

## 2. 主运行循环

```text
1. 接收用户目标。
2. 生成 GoalSpec。
3. 构建初始任务计划。
4. 选择输出策略。
5. 检测重大决策点，并在配置策略要求时询问用户。
6. 当阈值、阶段边界或交接策略要求时压缩上下文。
7. 准备工作区。
8. 分配就绪任务。
9. 智能体使用允许的工具执行工作。
10. 运行时记录产物和事件。
11. 运行验证。
12. 如果验证通过，进入评审并保留。
13. 如果验证失败，触发自动纠错。
14. 如果纠错失败，回滚或标记阻塞。
15. 更新记忆。
16. 持续运行，直到完成、预算耗尽或被阻塞。
17. 生成最终报告。
```

## 3. 核心概念

### 3.1 GoalSpec

用户目标的结构化表示。

示例：

```json
{
  "goal": "构建一个本地 Markdown 知识库系统",
  "constraints": ["本地优先", "Markdown 导入", "语义搜索"],
  "target_outputs": ["web_app", "readme", "tests"],
  "definition_of_done": [
    "可以导入 Markdown 文件夹",
    "可以创建可搜索索引",
    "可以带引用地问答",
    "可以本地运行"
  ],
  "verification": ["unit_tests", "smoke_test", "ui_screenshot"]
}
```

### 3.2 Task

最小可调度工作单元。

```json
{
  "id": "T-001",
  "title": "实现 Markdown 导入器",
  "role": "CoderAgent",
  "status": "ready",
  "dependencies": [],
  "acceptance": [
    "递归扫描 .md 文件",
    "提取标题、路径和正文",
    "具备单元测试"
  ],
  "artifacts": ["src/importer.ts", "tests/importer.test.ts"]
}
```

### 3.3 Experiment

一次受控的系统改进尝试。

```json
{
  "id": "EXP-042",
  "idea": "增加混合检索",
  "baseline": "仅向量搜索",
  "candidate": "BM25 加向量搜索再加 rerank",
  "evaluator": "eval/search_quality.json",
  "metrics_before": {"hit_rate": 0.62},
  "metrics_after": {"hit_rate": 0.71},
  "decision": "keep"
}
```

### 3.4 Artifact

任何持久化输出：

- 源代码。
- 补丁。
- 测试。
- 报告。
- PDF。
- 截图。
- 调研笔记。
- 评估结果。
- 记忆条目。

### 3.5 DecisionPoint

一个会实质影响结果的重大分支点。

```json
{
  "id": "D-003",
  "question": "这个工具应该优先采用哪种输出形式？",
  "recommended": "local_web_app",
  "options": [
    {
      "id": "local_web_app",
      "label": "本地 Web 应用",
      "tradeoff": "最适合反复交互使用，但前端工作量更高"
    },
    {
      "id": "cli",
      "label": "CLI",
      "tradeoff": "构建和自动化最快，但对非技术用户不够友好"
    },
    {
      "id": "pdf_report",
      "label": "PDF 报告",
      "tradeoff": "最适合分享结果，但不适合持续操作"
    }
  ],
  "default": "local_web_app",
  "granularity_required": "balanced",
  "impact": {
    "scope": "medium",
    "budget": "medium",
    "risk": "low",
    "quality": "high"
  }
}
```

决策管理器会根据配置的决策颗粒度，决定询问用户、自动选择推荐项，还是延后决策。

### 3.6 ContextSnapshot

一种紧凑、机器可读的摘要，使同一个智能体或另一个智能体能在不携带完整对话历史的情况下继续长任务。

```json
{
  "goal": "构建一个密码测试工具",
  "definition_of_done": ["可用的本地 UI", "强度评分", "清晰的隐私行为"],
  "accepted_decisions": ["本地优先", "默认不使用在线泄露 API"],
  "active_tasks": ["T-004", "T-007"],
  "modified_files": [
    {"path": "src/scoring.ts", "reason": "增加熵估算和策略评分"}
  ],
  "verification": [
    {"command": "npm test", "result": "passed"}
  ],
  "failures": [
    {"summary": "移动端 UI 溢出", "status": "fixed"}
  ],
  "research_claims": [
    "密码工具应区分强度估算和真实泄露检测"
  ],
  "next_actions": ["增加生成器测试", "运行 UI 截图检查"]
}
```

ContextSnapshot 由 `/compact`、阶段转换、交接和自动上下文预算策略产生。

### 3.7 Command

一种具名可复用工作流。

```json
{
  "name": "brainstorm",
  "description": "生成并排序产品或实现想法",
  "arguments": ["topic", "constraints"],
  "allowed_tools": ["read_memory", "query_web", "create_task", "create_decision"],
  "expected_artifacts": ["brainstorm_report.md", "candidate_tasks.json"]
}
```

命令可以由用户调用，也可以在策略允许时由智能体调用。

## 4. 智能体角色

### 4.1 GoalSpecAgent

将用户输入转换为结构化目标。

输出：

- `goal_spec.json`
- 假设
- 必要时的开放问题

### 4.2 PlannerAgent

创建里程碑和任务。

输出：

- `task_plan.json`
- 依赖图
- 第一轮迭代计划

### 4.3 ArchitectAgent

选择实现架构。

输出：

- 技术栈
- 模块边界
- 数据流
- 约束

### 4.4 ResearchAgent

将外部知识转化为可执行假设。

子角色可以包括：

- ResearchScout
- PaperReader
- IdeaSynth
- ExperimentDesigner
- CitationTracker

输出：

- 调研笔记
- 观点
- 证据
- 实现想法
- 实验计划

### 4.5 CoderAgent

在隔离工作区中实现范围明确的任务。

输出：

- 代码补丁
- 测试
- 实现说明

### 4.6 UIExperienceAgent

决定并实现合适的体验产物。

它不应该盲目创建网页，而是选择最适合的媒介：

- Web 应用。
- CLI。
- TUI。
- 桌面应用。
- PDF 报告。
- Markdown 知识库。
- 仪表盘。
- API 服务。

输出：

- 输出媒介建议
- 交互模型
- 页面或报告结构
- UI 实现任务
- 视觉验收条件

### 4.7 TesterAgent

创建并运行验证。

输出：

- 测试计划
- 测试文件
- 测试结果
- 复现步骤

### 4.8 ReviewerAgent

在保留或合并前评审补丁。

输出：

- 评审发现
- 风险评估
- 合并建议

### 4.9 AutoCorrectionAgent

处理失败和修复循环。

输出：

- 失败摘要
- 根因假设
- 修复补丁
- 重试决策

### 4.10 MemoryAgent

存储有用知识。

输出：

- 项目记忆
- 用户偏好记忆
- 实验经验
- 可复用模式

### 4.11 ReleaseAgent

打包最终输出。

输出：

- README
- 运行说明
- 发布说明
- 最终报告

## 5. 状态机

每次运行都经过受控状态。

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

允许的转换：

- 检查失败时，`VERIFY -> REPAIR`。
- 修复后，`REPAIR -> VERIFY`。
- 检测到重大分支决策时，`PLAN -> DECIDE` 或 `DESIGN -> DECIDE`。
- 用户选择或默认选择后，`DECIDE -> PLAN`、`DECIDE -> DESIGN` 或 `DECIDE -> IMPLEMENT`。
- 当目标宽泛、有创意或存在多个可行方向时，`PLAN -> BRAINSTORM`。
- 当候选方向需要用户操盘时，`BRAINSTORM -> DECIDE`。
- 当系统可以安全选择方向时，`BRAINSTORM -> PLAN`。
- 还有任务时，`KEEP_OR_DISCARD -> IMPLEMENT`。
- 完成时，`KEEP_OR_DISCARD -> REPORT`。
- 当预算或安全规则阻止继续时，任何状态都可以转到 `BLOCKED`。

## 6. 决策管理

决策管理器用于避免两个糟糕极端：

- 系统在没有理解用户意图的情况下，盲目做出重大产品或架构选择。
- 系统因为每个小实现细节都打断用户。

决策颗粒度可配置：

```text
autopilot：只在安全关键或不可逆决策上询问
balanced：在重大产品、架构、预算或隐私决策上询问
collaborative：更频繁地询问产品和 UX 选择
manual：重要变更或范围扩展前都先询问
```

决策检测信号：

- 多个可行产品方向会带来不同用户结果。
- 相比原始目标有较大范围扩展。
- 预算或时间显著增加。
- 涉及隐私、安全或数据敏感性。
- 涉及不可逆文件系统、部署或外部服务操作。
- 技术选择会强烈影响维护成本或用户体验。
- 调研结果揭示了多个竞争性实现方案。

决策请求格式：

```json
{
  "question": "密码测试工具是否应该包含泄露列表检查？",
  "recommended": "local_optional_import",
  "options": [
    {
      "id": "no_breach_check",
      "label": "不做泄露检查",
      "tradeoff": "更简单且完全本地，但现实风险提示更弱"
    },
    {
      "id": "local_optional_import",
      "label": "本地可选导入",
      "tradeoff": "用户提供本地列表时隐私安全，但设置更复杂"
    },
    {
      "id": "online_api",
      "label": "在线 API",
      "tradeoff": "更方便，但引入隐私和网络依赖问题"
    }
  ],
  "default": "local_optional_import"
}
```

每次决策都会写入事件日志和项目记忆。后续智能体必须把已接受决策视为约束。

## 7. 上下文压缩

上下文压缩是长任务运行时的一等机制。

触发策略：

```text
manual：用户或智能体调用 /compact
budget：上下文使用量超过阈值，例如 70% 或 85%
phase：调研、实现、评审或发布阶段完成
handoff：工作被委派给另一个智能体或留待未来恢复
```

压缩必须保留：

- 用户目标和不可协商约束。
- 完成定义。
- 已接受和已拒绝的重大决策。
- 任务状态。
- 修改过的文件和原因。
- 测试和评估命令。
- 失败、修复和回滚决策。
- 影响实现的调研发现。
- 未解决风险和下一步行动。

压缩应避免保留：

- 已经摘要过的原始命令噪声。
- 磁盘上已有的大段文件内容。
- 对未来没有意义的死路探索。
- 不影响实现的重复讨论。

`/compact` 命令接受聚焦指令：

```text
/compact focus on API design and changed files
/compact preserve UI feedback and unresolved layout risks
/compact prepare a handoff for ReviewerAgent
```

输出应同时面向人类和机器可读。机器可读部分应保存为 `ContextSnapshot`。

## 8. 命令工作流设计

命令用于封装可重复的智能体工作流。

初始命令集：

```text
/init
/plan
/brainstorm
/research
/compact
/decide
/review
/debug
/handoff
```

### 8.1 Init 命令

`/init` 将一个目录转换为 agent-ready 工作区。

它创建用户、项目、运行时和智能体之间的根契约。这是 harness 工程问题：智能体在安全执行长任务之前，需要稳定入口、明确约束、已知验证命令和持久状态。

工作流：

```text
1. 检查工作区形态。
2. 检测项目类型、技术栈、包管理器和已有文档。
3. 检测可能的测试、构建、lint、类型检查和运行命令。
4. 构建重要文件和目录的项目地图。
5. 创建或更新根指导文件。
6. 创建初始任务看板和上下文快照。
7. 创建默认运行时策略。
8. 只有在重大初始化选择不明确时才询问用户。
```

根指导布局：

```text
AGENTS.md
.agent/
  project.json
  policies.json
  context/
    root_snapshot.json
  tasks/
    backlog.json
  runs/
  memory/
```

`AGENTS.md` 应包含人类可读指导：

```text
项目目的
非目标
架构笔记
构建/测试/运行命令
代码约定
UI/设计约定
安全边界
决策颗粒度
智能体操作规则
```

`.agent/project.json` 应包含机器可读元数据：

```json
{
  "name": "mult-agent-code",
  "workspace_type": "planning_workspace",
  "languages": ["markdown"],
  "package_managers": [],
  "commands": {
    "test": null,
    "lint": null,
    "build": null,
    "run": null
  },
  "important_paths": ["docs/", "docs/zh/"],
  "protected_paths": [".env", "secrets/", ".git/"],
  "decision_granularity": "balanced"
}
```

`/init` 必须具备幂等性。它可以更新生成区域，但不能在没有明确批准的情况下覆盖用户手写指导。

当 `/init` 检测到重大分支决策，例如为新运行时选择 Python 还是 Node.js 时，它应该创建 `DecisionPoint`，而不是静默锁定某条路径。

### 8.2 Brainstorm 命令

`/brainstorm` 用于问题宽泛、有创意、规格不足或存在多个产品方向的场景。

工作流：

```text
1. 重述目标和约束。
2. 生成多样化候选方向。
3. 聚类重叠想法。
4. 按价值、可行性、成本、风险、新颖性和匹配度评分。
5. 识别必需的基线能力。
6. 推荐一个或多个路径。
7. 创建任务、实验或用户决策点。
```

输出：

```json
{
  "topic": "密码测试工具",
  "candidates": [
    {
      "name": "本地隐私优先的密码实验室",
      "score": 0.86,
      "strengths": ["有用", "安全", "可构建"],
      "risks": ["必须避免误导性的安全结论"]
    }
  ],
  "recommended": "本地隐私优先的密码实验室",
  "created_tasks": ["T-010", "T-011"],
  "decision_points": ["D-004"]
}
```

`/brainstorm` 不应直接实现代码。它产出方向、选项、任务和决策点。

### 8.3 Handoff 命令

`/handoff` 为另一个智能体或未来会话创建续接包。

它应包含：

- ContextSnapshot。
- 当前任务看板。
- 最近 diff。
- 验证状态。
- 已知风险。
- 推荐的下一条命令。

## 9. Harness 工程原则

运行时应该被设计成包裹不稳定模型工作者的 harness。它的职责是让智能体行为可观测、有边界、可恢复、可验证。

核心 harness 原则：

- 稳定根上下文：每次运行都从根指导文件和当前上下文快照开始。
- 显式状态：目标、任务、决策、补丁、工具调用和评估都存为持久产物。
- 窄工具：尽可能使用结构化工具，而不是只给原始 shell。
- 权限边界：运行时强制执行角色、状态和路径权限。
- 阶段门禁：规划、实现、验证、评审、保留/丢弃是不同关卡。
- 恢复路径：失败编辑可以回滚、重试或升级。
- 预算控制：token、时间、实验和工具预算都显式化。
- 交接能力：长任务可以压缩并恢复，不丢失意图。
- 用户操盘：重大分支决策变成 `DecisionPoint` 对象。
- 根文件纪律：项目级指导保存在稳定文件中，而不是只存在于临时聊天上下文里。

## 10. 工具设计

工具应该结构化、窄职责、可观测。

初始工具：

```text
read_file
list_files
search_code
apply_patch
run_command
run_tests
run_lint
run_typecheck
create_worktree
diff_workspace
rollback_workspace
query_web
query_docs
take_screenshot
write_memory
read_memory
create_task
update_task
submit_artifact
```

工具响应格式：

```json
{
  "ok": true,
  "summary": "3 个测试通过",
  "data": {},
  "warnings": [],
  "error": null
}
```

## 11. 权限模型

权限基于角色和状态共同决定。

示例：

```json
{
  "CoderAgent": {
    "allowed_tools": ["read_file", "search_code", "apply_patch", "run_tests"],
    "write_scope": "assigned_workspace"
  },
  "ReviewerAgent": {
    "allowed_tools": ["read_file", "search_code", "diff_workspace"],
    "write_scope": "none"
  },
  "ResearchAgent": {
    "allowed_tools": ["query_web", "query_docs", "write_memory", "create_task"],
    "write_scope": "research_artifacts"
  }
}
```

高风险工具调用由运行时拦截。

## 12. 工作区策略

MVP：

- 一个主工作区。
- 一个临时实现工作区。
- 在保留/丢弃前检查补丁 diff。

未来：

- 每个智能体一个 worktree。
- 合并队列。
- 冲突解决器。
- 容器隔离。

推荐布局：

```text
.agent/
  project.json
  policies.json
  context/
    root_snapshot.json
    handoffs/
  runs/
    run-2026-04-27-001/
      goal_spec.json
      task_plan.json
      events.jsonl
      experiments.jsonl
      final_report.md
  memory/
  workspaces/
  artifacts/
```

## 13. 记忆设计

记忆分层：

```text
用户记忆：偏好和长期目标。
项目记忆：架构和决策。
任务记忆：当前活跃上下文。
实验记忆：哪些有效，哪些失败。
调研记忆：观点、证据、引用。
决策记忆：用户选择和被拒绝的备选方案。
上下文记忆：压缩快照和交接包。
```

MVP 存储：

- SQLite 存结构化记录。
- 文件系统存产物。

未来存储：

- 向量数据库用于语义检索。
- 知识图谱用于实体关系。

## 14. 评估设计

系统同时评估结果和执行轨迹。

结果评估：

- 测试通过。
- 构建通过。
- 应用可以启动。
- UI 可用。
- 报告完整。
- 指标提升。

轨迹评估：

- 工具调用相关。
- 智能体没有陷入循环。
- 智能体没有绕过规则。
- 范围保持受控。
- 成本在预算内。
- 失败被正确处理。

## 15. 自动纠错设计

失败修复循环：

```text
capture_failure
  -> summarize_evidence
  -> propose_hypotheses
  -> choose_minimal_patch
  -> apply_patch
  -> rerun_evaluator
  -> keep_or_rollback
```

重试策略：

```text
max_retries_per_task: 3
max_retries_per_failure_type: 2
rollback_on_regression: true
escalate_to_user_on_safety_risk: true
```

## 16. 调研循环设计

调研流程：

```text
research_question
  -> source_discovery
  -> source_filtering
  -> claim_extraction
  -> evidence_mapping
  -> hypothesis_generation
  -> experiment_design
  -> task_creation
```

调研输出必须可执行。有价值的调研结果应创建一个或多个：

- 实现任务
- 实验任务
- 架构决策
- 记忆条目
- 报告章节

## 17. UI/体验设计

UI/Experience 智能体根据任务适配度选择输出形式。

决策因素：

- 用户是否需要反复和数据交互？
- 输出是用于阅读还是操作？
- 是否需要实时状态？
- 是否需要视觉检查？
- 是否需要分享？
- 是否自动化比界面更重要？

示例：

```text
知识库 -> 本地 Web 应用
批量文件重命名 -> 带预览的桌面应用或 CLI
研究摘要 -> PDF 加 Markdown 源文件
智能体监控 -> 仪表盘
数据清洗 -> CLI 加报告
```

## 18. 模型提供商设计

使用提供商抽象层。

```text
ModelClient
  -> chat()
  -> tool_call()
  -> embed()
  -> rerank() 可选
```

目标提供商：

- 智谱。
- MiniMax。
- DeepSeek。
- OpenRouter。
- 本地 OpenAI-compatible 服务。

模型路由：

```text
planning: 强模型
architecture: 强模型
coding: 中等或强模型
review: 强模型
summarization: 便宜模型
classification: 便宜模型
embedding: embedding 模型
```

## 19. MVP 实施计划

### 阶段 1：运行时骨架

- CLI 入口。
- `/init` 命令。
- 运行目录创建。
- GoalSpec 生成。
- 事件日志。
- 基础任务看板。
- 基础决策管理器。
- 基础命令注册表。
- 上下文快照写入器。

### 阶段 2：工具注册表

- 文件工具。
- 搜索工具。
- 补丁工具。
- 命令和测试工具。
- 工具调用日志。

### 阶段 3：智能体循环

- PlannerAgent。
- CoderAgent。
- TesterAgent。
- ReviewerAgent。
- Reporter。

### 阶段 4：保留/丢弃循环

- 工作区 diff。
- 验证命令。
- 实验日志。
- 失败回滚。

### 阶段 5：调研和 UI 智能体

- 调研任务生成。
- UI 输出建议。
- Web/PDF/报告任务创建。

### 阶段 6：记忆

- SQLite 记忆。
- 运行摘要。
- 相关记忆检索。

## 20. 开放设计问题

1. 第一版实现应该使用 Python 还是 Node.js？
2. 是否从一开始就使用 Git worktree？
3. 第一版 UI 应该是仪表盘，还是只生成最终报告？
4. 默认模型提供商应该是哪一个？
5. 调研应该使用 Web 搜索 API、本地论文语料，还是两者都用？
6. 对文件编辑和 shell 命令的人类审批应该多严格？
7. 默认决策颗粒度应该是 `autopilot`、`balanced`、`collaborative` 还是 `manual`？
8. 自动上下文压缩应该使用什么触发阈值？
9. 哪些命令允许智能体在没有用户批准的情况下自行调用？
10. 默认应该生成哪些根文件，哪些保持可选？

## 21. 推荐的第一版技术选择

第一版真实实现建议：

- 语言：Python 用于编排。
- 存储：SQLite 加 JSONL 事件日志。
- 工作区：目标项目是 Git 仓库时使用 Git worktree，否则使用临时副本。
- 模型 API：OpenAI-compatible 适配器。
- CLI：Typer 或 Click。
- Web UI 后置：核心循环跑通后再使用 FastAPI 加 React，或先做简单本地仪表盘。
- 补丁格式：unified diff。
- 报告：先 Markdown，后 PDF。
