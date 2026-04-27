# 多智能体自主开发系统 - 运行时命令与任务拆解

## 1. 文档目的

本文档定义运行时命令规格和 PlannerAgent 的任务拆解原则。

命令不是 prompt 快捷方式，而是可复用、可观测、可审计的工作流。任务拆解不是简单列清单，而是把目标切成大小适中、可验收、有明确产物的执行单元。

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

## 3. 初始命令集

### 3.1 `/init`

目的：

将目录初始化为 agent-ready 工作区。

输出产物：

- `AGENTS.md`
- `.agent/project.json`
- `.agent/policies.json`
- `.agent/context/root_snapshot.json`
- `.agent/tasks/backlog.json`

验收：

- 空目录可初始化。
- 已有目录可初始化。
- 重复运行安全。
- 不覆盖用户手写内容。

Agent 自调用：

默认不允许。通常由用户或首次运行流程触发。

### 3.2 `/plan`

目的：

将用户目标转化为结构化目标规格和任务计划。

输出产物：

- `goal_spec.json`
- `task_plan.json`
- 更新后的任务看板。

验收：

- 目标不只是原句复述。
- 包含完成定义。
- 包含验证策略。
- 对模糊目标给出合理假设。

### 3.3 `/brainstorm`

目的：

对宽泛、创意型或欠规格目标进行发散和收敛。

流程：

```text
generate candidates
  -> cluster
  -> score
  -> select recommendation
  -> create tasks or decision points
```

评分维度：

- 用户目标匹配度。
- 可行性。
- 实现成本。
- 使用价值。
- 风险。
- 新颖性。
- 验证难度。

### 3.4 `/research`

目的：

将外部资料、论文、开源项目或行业实践转化为可执行假设。

质量要求：

- 观点必须带来源或明确标记为模型推断。
- 调研必须转化为任务、实验、约束或决策点。
- 不允许只输出泛泛摘要。

### 3.5 `/compact`

目的：

压缩上下文，支持长任务续航和智能体交接。

必须保留：

- 目标。
- 完成定义。
- 用户决策。
- 活跃任务。
- 修改文件。
- 验证结果。
- 失败修复。
- 未解决风险。
- 下一步行动。

### 3.5.1 `/execute`

目的：

消费当前 run 中可执行的 `ready` 任务，驱动 CoderAgent 生成工具调用计划并执行。

输入：

- `run_id` 可选，默认最新 run。
- `max_tasks` 控制单次最多执行多少个任务。

输出产物：

- 更新后的 `task_plan.json`。
- 同步后的 `.agent/tasks/backlog.json`。
- `events.jsonl`。
- `tool_calls.jsonl`。
- `model_calls.jsonl`。
- `cost_report.json`。

状态推进：

```text
ready -> in_progress -> testing -> reviewing -> done
```

工具失败、验证失败或模型返回非法行动时进入 `blocked`，等待 `/debug`、修复循环或用户决策。

约束：

- 只能使用任务 `allowed_tools` 与工具注册表同时允许的工具。
- 默认不做真实网络调研、不读取密钥、不部署。
- 每次执行必须累计成本报告，不能覆盖已有模型调用和 token 记录。

### 3.6 `/decide`

目的：

创建用户决策点。

决策请求必须包含：

- 问题。
- 推荐选项。
- 2-4 个选择。
- 每个选择的取舍。
- 默认选择。
- 对预算、范围、风险、质量的影响。

### 3.7 `/review`

目的：

评审代码、需求覆盖、UX、测试和风险。

评审维度：

- 正确性。
- 需求覆盖。
- 测试充分性。
- 安全风险。
- 体验问题。
- 范围膨胀。
- 可维护性。

### 3.8 `/debug`

目的：

分析失败并提出最小修复。

流程：

```text
collect evidence
  -> summarize failure
  -> generate hypotheses
  -> choose minimal fix
  -> rerun verification
```

### 3.9 `/handoff`

目的：

为另一个智能体或未来运行创建续接包。

必须包含：

- 当前目标。
- 当前状态。
- 活跃任务。
- 已接受决策。
- 最近 diff。
- 验证状态。
- 风险。
- 推荐下一步。

## 4. 命令预算建议

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

## 5. 任务拆解原则

好的任务拆解应该做到：

- 不太大，大到无法一次实现和验收。
- 不太小，小到调度成本高于实现价值。
- 每个任务都有明确产物。
- 每个任务都有可验证验收条件。
- 任务之间依赖清晰。
- 能支持多 agent 协作和后续自动评估。

建议单任务大小：

```text
预计实现时间：15-90 分钟
文件改动：1-5 个文件
验收条件：2-6 条
依赖数量：0-3 个
输出产物：1-4 个
```

## 6. 标准任务结构

```json
{
  "task_id": "task-0001",
  "title": "实现密码强度评分模块",
  "description": "根据长度、字符多样性和常见弱密码规则计算评分，并返回解释",
  "role": "CoderAgent",
  "priority": "high",
  "depends_on": [],
  "acceptance": [
    "输入密码后返回 0-100 分",
    "返回至少 2 条可解释原因",
    "包含常见弱密码检测",
    "包含单元测试"
  ],
  "expected_artifacts": [
    "src/scoring.ts",
    "tests/scoring.test.ts"
  ],
  "verification": [
    "npm test"
  ]
}
```

## 7. 任务类型

- Research Task：调研和证据收集。
- Product Task：需求扩展和产品判断。
- Architecture Task：技术方案和模块边界。
- Implementation Task：代码实现。
- UI/Experience Task：界面、报告或交互产物。
- Verification Task：测试和评估。
- Repair Task：失败修复。
- Documentation Task：README、报告、使用说明。

## 8. 拆解方法

### 8.1 能力链路拆解法

适合软件工具：

```text
输入
  -> 解析/导入
  -> 核心处理
  -> 存储/状态
  -> 输出/展示
  -> 验证
  -> 文档
```

### 8.2 风险优先拆解法

适合不确定性高的任务。

先拆：

- 技术可行性验证。
- 第三方依赖验证。
- 性能验证。
- 隐私和安全验证。
- UX 输出形态验证。

### 8.3 垂直切片拆解法

适合 MVP。

优先做一条完整闭环：

```text
最小输入
  -> 最小处理
  -> 最小输出
  -> 最小测试
  -> 最小文档
```

## 9. 任务质量评分

每个任务生成后应打分：

```text
clarity_score：描述是否清晰
testability_score：是否可验收
size_score：大小是否合适
dependency_score：依赖是否清楚
artifact_score：产物是否明确
risk_score：风险是否可控
```

建议阈值：

```text
clarity_score >= 0.75
testability_score >= 0.75
size_score >= 0.70
artifact_score >= 0.75
```

低于阈值时，PlannerAgent 应重写任务。

## 10. 拆解反模式

坏任务：

```text
优化搜索。
界面好看。
实现完整知识库。
接入在线泄露密码 API。
```

好任务：

```text
实现 BM25 + 向量混合搜索，并用固定查询集评估命中率。
在 1366x768 下核心按钮不重叠，搜索结果列表可滚动，主要流程可完成。
实现 Markdown 导入器。
创建关于泄露检测方案的 DecisionPoint，比较不接入、本地导入和在线 API。
```

## 11. PlannerAgent 输出要求

PlannerAgent 输出任务计划时必须包含：

- 任务列表。
- 依赖关系。
- 阶段划分。
- 每个任务验收条件。
- 每个任务预期产物。
- 每个任务建议角色。
- 重大决策点。
- 风险任务标记。
- MVP 任务和后续任务区分。

## 12. 任务拆解验收

一个任务计划合格的标准：

- 每个 must 需求至少被一个任务覆盖。
- 每个任务都有验收条件。
- 每个任务都有预期产物。
- 高风险选择有 DecisionPoint。
- 第一阶段任务能形成可运行闭环。
- 暂缓需求进入后续阶段，而不是消失。
