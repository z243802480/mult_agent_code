# Asteria Studio 失败复盘与重做方案

## 1. 结论

当前 Studio 原型不合格。它不是一个面向用户的智能体工作区，而是把后台命令、证据面板、假对话和临时按钮拼在一起的混合界面。

必须停止在当前 UI 上继续缝补。下一步应保留可用的后端能力探索，重做产品信息架构和前端体验。

## 2. 主要失败

### 2.1 产品模型错误

用户需要的是类似 Codex / Claude Code 的工作区：

- 一个明确的对话线程。
- 用户输入目标后立即得到响应。
- 后台执行过程可见。
- 权限请求清楚。
- 文件修改、产物、证据可预览。
- 可以继续追问、修正、批准、拒绝、恢复。

当前 Studio 做成了：

- Dashboard 入口。
- 多个动作面板。
- 后台观测和用户工作混在一起。
- 对话只是规则回复器。
- 真正 runtime 的 `init / plan / run / execute / review / resume / decide / promotions` 没有被组织成清晰用户流程。

### 2.2 假智能体感太强

用户说“你好”或“帮我计划青岛怎么玩”，系统应该像智能体一样先确认、理解目标、开始计划或说明需要什么权限。

当前实现的问题：

- 对话层是规则分支，不是真实 Agent 会话。
- 回复和 runtime job 是割裂的。
- 用户输入没有形成一个可持续的 session。
- UI 不清楚当前是在聊天、规划、执行还是查看后台证据。

### 2.3 执行反馈不成体系

成熟 agent 工作区的核心是 activity thread，而不是 dashboard。

当前实现的问题：

- job/activity 是后来补的，不是主架构。
- stdout/stderr 裸露，缺少“正在做什么”的语义层。
- 没有步骤状态：thinking / planning / running tool / waiting approval / reviewing / done。
- 没有把 run evidence 转成用户能理解的 timeline。

### 2.4 权限模型没有产品化

当前只是 checkbox 和风险文案。

应该有：

- 明确的 permission card。
- 本次动作会读什么、写什么、运行什么命令。
- 允许一次 / 允许本会话 / 拒绝。
- 危险动作默认不执行。
- 所有审批写入 evidence。

### 2.5 文件和产物体验错误

当前文件列表像后台调试工具。

应该是：

- 本次任务生成/修改了哪些文件。
- diff 预览。
- 报告预览。
- 证据包导出。
- 与对话消息和 run step 关联。

### 2.6 工程实现混乱

当前实现暴露出几个硬问题：

- `main.tsx` 过大，组件边界混乱。
- `server.mjs` 过大，API、job、文件读取、conversation、runtime command 混在一起。
- 中文文案出现 mojibake，说明文件编码或工具链处理有问题。
- 前端状态模型混乱：conversation、job、action、feed、dashboard 同时在首页抢主语。
- 缺少 UI-level 测试或截图验收。

## 3. 重做原则

### 3.1 首页只做 Workspace

首页只允许出现：

- Sidebar：sessions / projects / settings。
- Main Thread：对话和 activity。
- Composer：用户输入目标。
- Inspector：当前选中消息、命令、权限、文件、证据。

Dashboard 不允许出现在首页。它只能作为后台 Observability 页面。

### 3.2 对话必须是真入口

用户输入后必须在 100ms 内出现：

- 用户消息。
- assistant acknowledgement。
- activity placeholder。

如果需要真实模型或 runtime，activity 卡片必须显示：

- queued
- planning
- running
- waiting approval
- reviewing
- completed / failed

### 3.3 Runtime 是执行内核，Studio 是交互壳

Studio 不重新实现 agent。

Studio 应调用 runtime：

- `init`
- `plan`
- `run`
- `execute`
- `review`
- `resume`
- `decide`
- `promotions`
- `evidence-bundle`

但必须把它们包装成用户任务流，而不是把命令列表扔给用户。

### 3.4 Evidence 是后台能力

证据必须记录，但不应该抢主界面：

- Activity 需要引用 evidence。
- Inspector 可以显示证据。
- Observability 页面可以展示 dashboard。
- 导出 evidence bundle 是明确动作。

## 4. 新信息架构

```text
Studio
  Workspace
    Session sidebar
    Main thread
      User message
      Assistant message
      Activity step
      Permission request
      File change summary
      Final report
    Composer
      natural language goal
      mode: plan / run / continue
      permission policy
    Inspector
      selected step details
      command
      stdout/stderr
      file diff / artifact preview
      evidence refs

  Observability
    Gate status
    Model routes
    Acceptance
    Package/doctor
    Evidence bundle

  Settings
    Workspace root
    Runtime root
    Routes present
    Permission defaults
```

## 5. 下一轮实现边界

第一刀只做一个真正可用的 Workspace，不做 dashboard：

1. 删除当前首页混合布局。
2. 建立 `StudioSession` 数据模型：
   - `session_id`
   - `messages`
   - `activities`
   - `permissions`
   - `artifacts`
3. 用户输入目标后创建 session message 和 activity。
4. 后端启动 runtime command job。
5. 前端轮询 job，并更新 activity 卡片。
6. plan 完成后展示：
   - 命令
   - 状态
   - stdout 摘要
   - 新/改文件
   - evidence refs
7. 写入型动作必须出现 permission card。

## 6. 验收标准

用这个任务验收：

```text
帮我计划一下如何去青岛玩
```

最低合格标准：

- 用户按 Enter 后立即看到自己的消息。
- 立即出现 assistant acknowledgement。
- 立即出现 activity：Planning with runtime。
- 能看到后台 job 状态变化。
- 完成后看到可读计划，而不是只看到 stdout。
- 如果失败，看到失败原因和重试/切换模型/导出证据的选项。

当前版本没有达到这个标准。
