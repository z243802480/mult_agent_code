# ADR-0024：干活的模型必须真正读回自己的持久记忆（对标成熟 agent 的上下文自觉）

- 状态：Accepted（2026-07-08）
- 关联：[ADR-0016 认知归模型/边界归状态 §3 证据型]、[ADR-0021 主线程即真实证据流]、`core/context_loader.py`、`core/active_goal_memory.py`、`commands/execute_command.py`
- 触发：用户观察运行中的 agent —— "重复写同一个文件、似乎没用过去的记忆、根本没用读当前目录的记忆"，对标 Claude Code 类成熟 agent 差距明显。

## 1. 背景（Context）

运行时**写**了一份结构化的长任务记忆 `ActiveGoalMemory`（`.asteria/memory/active_goal.md` + `.json`）：
`current_goal / overall_plan / completed_work / artifact_refs（已产出的文件）/ next_task / current_blockers`，
每个 run/review/accept 后由 `write_from_run` 刷新。但审计（Explore 全链路 grep）证实：这份记忆的**所有
读点只服务 status 展示 / chat 上下文 / orchestration 面板 / handoff brief**，
`execute_command._model_driven_prompts` 组装执行 prompt 时**一处不读**。

后果 —— 干活的模型（CoderAgent 立真身循环）**看不到自己上一段 run 的记忆**：resume / 续目标 / 多 task
冷启动时它是"失忆"重开的。它不知道 `snake.py` 已经产出过、不知道哪些 task 已 done、不知道 next_task 是什么。
表征就是用户看到的：**重复写同一个文件、把已完成的活重做一遍**。我们建了漂亮的记忆，却对唯一需要它的
消费者（doer）只字不提。这是与成熟 agent 最刺眼的差距之一。

（同一 turn 内模型有 observation history + `workspace_files` 快照，所以"重复写"主要发生在 **跨 run/跨 task
冷启动**；快照还受 20 文件/1200 字符上限、且冻结于 run 启动时。这两点单列为 §5 后续，本 ADR 只钉"读回记忆"。）

## 2. 决策（Decision）

在 `ContextLoader.load()`（执行 prompt 的 runtime_context 唯一来源，`execute_command.py:298` 调用，直通
`_model_driven_prompts` 的 `payload["runtime_context"]`）新增一个键 `active_goal`，由新 helper
`_active_goal()` 从 `ActiveGoalMemory.read_structured()` 投影出一份**有界、prompt 安全**的视图：
`current_goal / current_result / overall_plan[:12] / completed_work[:8] / artifacts_already_produced[:10]
/ next_task[:5] / current_blockers[:5]`。

- **best-effort**：记忆缺失/损坏 → 返回 `{}`，绝不阻塞上下文加载（`read_structured` 已有 JSON 损坏恢复）。
- **单点接入**：只在 ContextLoader 这一处 wire，同一 runtime_context 天然同时惠及 planner / worker 路径。
- **有界**：所有列表截断，避免撑爆 prompt；沿用既有 idiom（memory/snapshot/handoff 都这么做）。

## 3. ADR-0016 合规

- **§1 认知归模型**：本改动**不做任何认知**——不替模型判断"该不该重写、算不算做完"，只把**客观的持久事实**
  （已产出哪些文件、哪些 task 已 done）作为上下文喂进模型的决策空间。要不要据此跳过重写，由模型自己涌现。
- **§2 边界归状态**：记忆的读写是确定性持久化边界（本就属状态层）；把它接到 doer 是补齐边界喂料，不是新增
  状态机分支。
- **§3 证据型**：喂的是可审计的真实记录（`write_from_run` 落盘的 artifacts/completed_work），非编造标量。

## 4. 一致性检查（Conformance）

- [x] 纯增量上下文键；无删除、无 schema 迁移、无 flag。
- [x] 记忆缺失/损坏返回 `{}`，零行为变化（既有 context_loader / execute 套件全绿：6 + 25）。
- [x] 新增正向测试：记忆存在 → `active_goal` 浮现 current_goal/artifacts/completed_work/overall_plan；
  缺失 → `{}`。
- [x] 未触 `active_goal_memory.py` 写路径 / 执行循环认知（只读消费）。

## 5. 后续（同主题·分片续做）

对标成熟 agent 的"上下文自觉"还差两刀，单列避免本刀膨胀：

- **#1 重复写的直接止血**：
  - ✅ **observation 显式化已落地（2026-07-08）**：`WriteFileTool.run` 在写前已知 `resolved.exists()`，
    据此把 summary 从 `Wrote file: X` 改为 `Created new file: X (N bytes) — it now exists at X` /
    `Overwrote existing file: X ...`，并在 `data` 带 `operation`（created/modified）+ `existed_before`。
    弱模型现在能分辨新建 vs 覆盖、且明知"文件现已存在"，不再盲目重发 write_file（同路径重写会硬失败
    于 `overwrite=False`）。+1 集成测试（created→modified 分辨）；tool_registry/execute/run/gateway
    共 85 测绿·ruff/mypy 净。
  - ⬜ **快照按 task 刷新仍待做**：`workspace_files` 快照冻结于 run 启动，多 task run 里后续 task 看不到
    前一 task 刚写的文件（active_goal 仅在 run 结束后刷新，补不上 run 内跨 task 的空窗）。→ 在
    `_model_driven_prompts` 前按当前工作区重扫 workspace_files（per-task 浅拷贝，勿污染共享 runtime_context）。
- ✅ **#3 项目记忆（AGENTS.md）有意接入已落地（2026-07-08）**：`ContextLoader.load()` 加 `root_guidance`
  键（`_root_guidance()` 读 `root/AGENTS.md`，字符预算 4000 远大于 workspace_files 的 1200），并从
  `_workspace_files` 里**排除 AGENTS.md**（避免正文重复 + 释放一个 20 文件槽位）。执行 prompt 现在**有意**
  读项目自己的指引，而非偶然截断泄漏。缺失→`{}`。+2 单测（浮现且不重复 / 无 AGENTS.md 时为 {}）；
  context_loader 8 绿 + context_injection/execute/planner 53 绿·ruff/mypy 净。（未加 CLAUDE.md：本项目
  CLAUDE.md 仅 `@import` AGENTS.md，AGENTS.md 是跨工具单一真源。）

## 6. 回退（Rollback）

删 `load()` 里的 `"active_goal"` 键与 `_active_goal()` helper 即完全回退。无 flag、无 schema、无持久化
格式变化，零成本。
