# 多智能体自主开发系统 - 测试策略

## 1. 文档目的

本文档定义如何测试这套多智能体自主开发系统。

测试目标不是验证单个模型回答是否漂亮，而是验证整个 agent runtime 是否能稳定完成长任务。

## 2. 测试金字塔

```text
Unit Tests
  -> Schema Tests
  -> Tool Tests
  -> Command Workflow Tests
  -> Agent Loop Tests
  -> End-to-End Scenario Tests
  -> Regression Benchmarks
```

## 3. 单元测试

覆盖对象：

- 数据模型。
- 状态机转换。
- 预算计算。
- 权限判断。
- 任务状态更新。
- 决策颗粒度判断。
- 上下文压缩选择逻辑。

示例：

- `DecisionManager` 在 `balanced` 模式下应升级隐私决策。
- `BudgetController` 超阈值时应阻止继续调用强模型。
- `TaskBoard` 不允许依赖未完成的任务进入 `ready`。

## 4. Schema 测试

所有核心产物必须有 schema 校验：

- `GoalSpec`
- `Task`
- `DecisionPoint`
- `ContextSnapshot`
- `Experiment`
- `RunReport`
- `CostReport`
- `ProjectConfig`
- `PolicyConfig`

测试重点：

- 必填字段。
- 枚举值。
- 默认值。
- 版本兼容。
- 错误提示。

## 5. 工具测试

每个工具都必须测试：

- 成功路径。
- 失败路径。
- 权限拒绝。
- 日志记录。
- 输出结构。
- 超时。

关键工具：

- `read_file`
- `search_code`
- `apply_patch`
- `run_command`
- `run_tests`
- `diff_workspace`
- `rollback_workspace`
- `write_memory`
- `read_memory`

## 6. 命令工作流测试

### 6.1 `/init`

测试：

- 空目录初始化。
- 已有项目初始化。
- 重复运行不覆盖手写内容。
- 生成 `.agent/` 结构。
- 正确检测项目类型。

### 6.2 `/plan`

测试：

- 简单目标生成 GoalSpec。
- 模糊目标扩展需求。
- 过大目标生成决策点。
- 输出任务计划。

### 6.3 `/brainstorm`

测试：

- 生成多个候选。
- 候选聚类。
- 评分排序。
- 创建任务或决策点。
- 预算超限时收敛。

### 6.4 `/compact`

测试：

- 保留关键目标和任务。
- 保留用户决策。
- 去除冗余日志。
- 可被后续 agent 读取。

### 6.5 `/debug`

测试：

- 捕获测试失败。
- 生成失败摘要。
- 提出修复假设。
- 超过重试次数停止。

## 7. Agent Loop 测试

测试智能体运行闭环：

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

## 8. 端到端场景测试

### 场景 1：密码测试工具

目标：

```text
做一个密码测试工具
```

期望：

- 自动扩展需求。
- 识别隐私和安全边界。
- 生成可运行工具。
- 有基础测试。
- 有最终报告。

### 场景 2：Markdown 知识库

目标：

```text
做一个本地 Markdown 知识库，支持搜索和问答
```

期望：

- 生成导入、索引、搜索、问答任务。
- 输出合适的 UI 形态建议。
- 至少实现 MVP 子集。

### 场景 3：批量文件重命名工具

目标：

```text
做一个批量重命名文件的小工具
```

期望：

- 形成 CLI/桌面/Web 决策点。
- 默认保护文件安全。
- 支持预览再执行。

### 场景 4：修复已有项目

目标：

```text
修复这个项目里明显的测试失败
```

期望：

- 自动运行测试。
- 定位失败。
- 尝试最小修复。
- 通过后生成 diff 和报告。

### 场景 5：上下文长任务续航

目标：

```text
连续执行多个阶段任务，中途强制 compact
```

期望：

- 压缩后不丢失目标、任务、决策。
- 后续阶段能继续。

## 9. 回归基准集

建立 `benchmarks/`：

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

## 10. 模型不稳定性的测试策略

由于模型输出不完全确定，测试不能只比较全文。

应使用：

- Schema 校验。
- 关键字段检查。
- 产物存在检查。
- 命令退出码。
- 测试通过率。
- 语义评分。
- 快照测试只用于稳定部分。

## 11. 成本测试

必须测试：

- 超预算停止。
- 接近预算降级。
- 上下文阈值触发压缩。
- 修复次数限制。
- 无产物调用比例过高时报警。

## 12. 安全测试

必须测试：

- 禁止读取 `.env`。
- 禁止删除大量文件。
- 禁止全局安装。
- 禁止远程 push。
- 禁止部署。
- 网络关闭时 ResearchAgent 正确降级。

## 13. 测试报告

每次测试运行生成：

```json
{
  "scenario": "password_tool",
  "status": "pass",
  "goal_eval": 0.82,
  "outcome_eval": 0.76,
  "trajectory_eval": 0.80,
  "cost_eval": 0.91,
  "failures": [],
  "artifacts": []
}
```

## 14. MVP 测试完成定义

MVP 测试通过的最低条件：

- `/init` 测试通过。
- `/plan` 测试通过。
- `/compact` 测试通过。
- 至少 2 个端到端场景通过。
- 成本阈值测试通过。
- 安全权限测试通过。
- 失败修复测试至少一个通过。
