# Asteria Studio 真实任务基准

## 1. 目的

当前 Studio 还不能交给真实用户内测。原因不是缺少更多按钮，而是还没有证明：

- runtime 能把通用用户目标组合成合理工作流。
- Studio 能把过程展示成用户看得懂的任务进展。
- 权限、模型反馈、文件产物、验证和下一步可以形成同一条会话线。
- 用户能选择 Project/Workspace，且 session、run、evidence、文件预览、Git 状态和输出目录都绑定到该 Workspace。
- 前台不是硬编码演示，也不是后台日志换皮。

因此先建立一套本地可重复的用户任务基准。它不替代真实模型验收，但作为进入内测前的最低门槛。

## 2. 基准任务

基准清单位于：

```text
benchmarks/studio_user_tasks.json
```

第一批任务覆盖五类：

- 通用规划：青岛三日旅行计划。
- 小代码任务：给 CLI 增加参数并补测试。
- 分析诊断：分析失败日志并给修复建议。
- 文档综合：整理零散需求为一页 PRD。
- 连续任务：继续上次未完成任务。

这些任务故意不是全是代码任务，因为 Studio 必须证明自己是用户侧智能体工作区，而不是只会包一层工程命令。

## 3. 最低交互标准

每个任务至少要能产生：

- Workspace：用户能看到当前 Workspace，并可从 Recent / Open folder 切换；切换后任务、session、文件视图、Git 状态和 runtime evidence 重新绑定。
- 用户消息：目标被持久化。
- 即时理解：前台立即显示 assistant acknowledgement。
- 任务进展：计划、模型流式反馈或执行状态可见。
- 权限或结果：权限模式可见；`ask_everything`、`reviewed_auto`、`auto` 的操作行为能被事件证据解释；写入/执行前按模式请求权限，或给出模型/最终结果。
- 文件与 Git：目标产物、diff、文件预览和 Git 状态来自当前 Workspace，不读取或污染其他 Workspace。
- 证据分层：命令、stdout、stderr、原始 runtime 细节进入 Inspector，不污染主线程。

用户主线程关注：

```text
理解目标 -> 制定计划 -> 执行 -> 核对 -> 结果 -> 下一步
```

Inspector 关注：

```text
runtime command
stdout/stderr
event refs
artifact refs
model/route/token telemetry
```

## 4. 命令

运行当前 Studio 会话基准：

```bash
python -m asteria_runtime studio-benchmark --root .
```

输出 JSON：

```bash
python -m asteria_runtime studio-benchmark --root . --json
```

只评估一个 Studio session：

```bash
python -m asteria_runtime studio-benchmark --root . --session-id session-xxx
```

## 5. 内测门槛

进入用户内测前至少满足：

- `studio-benchmark` 分数达到 0.80。
- 五个基准任务都用真实 UI 跑过并保留事件。
- 至少一个通用任务和一个代码任务使用真实 provider。
- Project/Workspace Switcher 跑通过 Recent、Open folder、切换已有项目、新建 session、继续旧 session 这几条路径。
- 三种权限模式至少各跑通一个任务片段，并能在 Inspector 看到对应 permission evidence。
- 主线程不出现大段裸 stdout。
- 失败任务必须有可读失败原因和下一步，而不是沉默或卡死。

## 6. 基准扩展要求

当前命令只评估 Studio 事件是否满足最低交互结构。后续要继续补：

- 从 runtime 原生产生 `user_progress` 事件，减少 Studio 对 stdout 的解释。
- 把基准结果和 capability profile 关联起来。
- 增加真实模型耗时、首 token、chunk 数、fallback、重试和用户等待时间统计。
- 增加 Playwright 截图验收，防止 UI 看起来仍然像后台 dashboard。

## 7. 当前实现状态

- `studio-benchmark` 已读取 `.asteria/studio/sessions/*/events.jsonl`，检查用户消息、即时反馈、进展、权限/结果和 Inspector 分离。
- 基准现在也读取 `.asteria/runs/*/user_progress.jsonl`，检查 runtime-native `model/tool/file/evidence` 通道覆盖。
- Studio server 已开始优先把 `user_progress.jsonl` 映射为前台事件：`model` channel 进入模型流式反馈，`tool` channel 进入工具执行，`file` channel 进入文件变化，证据引用保留在 Inspector。
- 运行中的 session 已支持在 final answer 前关联 active runtime run：server 会优先从 stdout/stderr 捕捉 run id，捕捉不到时按 job 启动时间发现最新带 `user_progress.jsonl` 的 run，并在轮询事件时合并实时进展。
- Inspector 已按 `Shell / Diff / Artifacts / Diagnostic` 分区展示选中事件，避免把命令输出、文件变化、证据引用和遥测混成一段原始 JSON。
- Evidence Explorer 已展示 User Progress，用于核对 Studio 看到的主线是否来自 runtime 真实过程，而不是 UI 硬编码演示。
- 当前基准仍是“准入诊断”，不是美观评分；只要五个真实用户任务没有跑通并留下过程证据，就不能宣布 Studio 已适合内测。

## 8. 下一步

1. 用五个基准任务跑真实会话，补齐 capability、权限、文件预览和继续迭代证据。
2. 将实时订阅从轮询升级为 SSE/WebSocket，降低延迟并减少前端猜测。
3. 在基准报告中增加 Workspace switcher、权限模式、Inspector 分区和文件/Git 视图覆盖检查，防止后续 UI 退回“后台日志换皮”。
