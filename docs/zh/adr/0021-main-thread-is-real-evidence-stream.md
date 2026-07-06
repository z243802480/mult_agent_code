# ADR-0021：主线程是真实证据流,不是 harness 自述过关（强化 0007 / 0012 / 0016）

**状态**：Proposed
**日期**：2026-07-06
**关系**：强化 [ADR-0007](0007-runtime-progress-as-product-main-path.md)（runtime_progress 是产品主路径）、
[ADR-0012](0012-session-transcript-as-studio-main-path.md)（会话转录是 Studio 主路径）、
[ADR-0016](0016-model-driven-cognition-conformance.md)（认知归模型 / 边界归状态）。不 supersede 任何一条。

## 背景

用户在真实 glm·minimax 栈上跑通中文编码案例后指出两个刺眼问题,复核后确认是同一个根因：

1. **主线程像"harness 在给自己发合格证"**：`理解目标 / 制定计划 / 执行迭代 1 / 运行完成 /
   task-0001 已完成，证据已通过验证` 这些**由 harness 用 agent 口吻写死的句子**冒充了"模型的回答"。
   用户原话:"为什么要把自己的过关输出出来。其他软件有这么干的？"——**没有**。Claude Code /
   Cursor / Copilot 主线程只有两类东西:①模型自己流式说的话;②**真实工具结果**(命令+输出、diff、
   报错)。状态提示("✓ 3 tests passed"、"Editing calc.py")绑在真实结果上,不是伪装成 agent 的旁白。

2. **假过关会盖掉模型的真话**：某次 multiply.py 任务被权限挡下、实际没生成,模型自撰的复盘诚实说
   "…文件列表中也未见 multiply.py,实际是否完成无法确认",但主线程显示的是确定性回退摘要
   `task-0001 已完成，证据已通过验证`——**harness 的假过关顶掉了模型的真话**。这比"多余"更糟。

### 真实数据诊断（run-20260705-0001）

真实的 per-action 证据**都存在**,只是**没进主转录**：

| 证据 | 真内容所在 | 进 user_progress(主线程) 了吗 |
| --- | --- | --- |
| Shell/验证命令+stdout/exit | `validation_results.jsonl`（command/returncode/stdout/stderr） | ✗ 只存"N/N 项通过"计数,无命令无输出 |
| Tool 调用参数+结果 | `tool_calls.jsonl` / `tool_observations.jsonl`（`Wrote file: calc.py`、`denied…`） | 半:名字+状态进,**完整参数/结果不进** |
| 文件 diff | `tool_observations.file_changes` / backup 工件 | 半:路径+操作进,**diff 不进** |
| 文档/上下文关联 | `context_mounts.jsonl` | ✗ **完全没有对应 user_progress 事件** |
| 模型真话/复盘 | `transcript_kind=final` 的 content_delta / `final_report.md` | 有,但被 harness 摘要在呈现层顶替 |

harness 自述注入点(节选,均可由真数据替代或直接删)：
`plan_command.py:194/247`(理解目标/制定计划)、`run_command.py:354/389`(执行迭代/运行完成)、
`task_attempt_runner.py:98/133/313-314`(开始验证/验证完成/`task-X completed with verified evidence`)、
`execute_command.py:2715/2831`(Worker action requested/proposed)、
`model_progress_sink.py:52/80/113`(Thinking/Drafting/Draft complete)。

## 决策

**主线程只渲染两类东西:模型的真话 + 每个真实动作的真实过程。凡是 harness 用 agent 口吻写死、
或替 agent 自证成功的句子,一律从主线程移除或降级为绑定真实结果的安静状态。**

三条可执行判据（对齐 ADR-0012:转录自包含,Studio 是转录的渲染器,不是跨文件 federate 的聚合器）：

1. **真内容灌进转录(enrich-at-emission)**：真实动作在 emit user_progress 时就带上可渲染的真内容——
   - 验证事件带**真实命令 + stdout/exit**(取自 `validation_results`),title/summary 由真实结果派生,
     不再写死"开始验证/验证完成"。
   - Tool 事件带**关键参数摘要 + 真实结果文本**(取自 observation),`tool_result` 的 content_delta = 真实输出。
   - 新增**文档/上下文关联**事件:挂载了哪些文档/简报(取自 `context_mounts`),在主线程作为一类过程卡。
   - 文件事件已有路径+操作;diff 仍在 Changes 面板(ADR-0012:单一 review 面,不散卡)。

2. **final 只用模型真话**：主线程的"回答"只取模型 final 的真实 content_delta;模型没产出就显示
   **中性的真实状态**(如"运行结束,未产出可展示的回答"),**绝不**用 `task-X completed with verified
   evidence` 这类 harness 自证句冒充回答。承载该自证句的 evidence 事件不得标成 `transcript_kind=final`。

3. **过关状态与模型自陈对账**：只有存在**独立真实校验结果**时才显示"验证通过"绿条;当模型 final 自陈
   未完成/未确认/被阻塞时,**不许**出现"验证通过"。绿条是证据呈现,不是 harness 背书。

**不做**(避免走偏)：不把 Studio 改成跨 sidecar 文件 federate 的聚合器(违反 ADR-0012 转录自包含);
不新增编排 Wave;不动 correctness_eval 作为证据的地位(它是证据不是闸,见 ADR-0016/0018)。

## 影响

- **后端**：`task_attempt_runner`(验证事件带真命令+输出、evidence 不再冒充 final)、
  `tool_execution_gateway`(tool 事件带参数+结果)、`runtime_profile_builder`/上下文挂载处(新增文档关联事件)、
  `plan_command`/`run_command`(阶段旁白降级为安静状态或由真数据派生)。删代码 > 加代码。
- **前端**：`TurnFinal` 只认模型真话(去掉 `step.summary` 的 harness 回退);验证/工具卡渲染真命令+输出;
  新增"文档关联"过程卡;`verifiedPass` 与模型自陈对账。多数组件(ToolCallCard/AggregateDiffChip/
  ThinkingBlock)已就位,主要是喂真数据 + 去顶替。
- **契约**：`user_progress` schema 需容纳验证事件的命令/输出字段与上下文关联事件类型;保持向后兼容。
- **验证**：同一中文编码案例端到端跑一遍,主线程每步 shell/tool/文档/验证都看得见真实过程,且模型自陈
  未完成时不出现假绿条。

## 实现进度（增量交付，逐刀真实运行验证）

- **切片 1 — evidence 不冒充 final（已做，验证）**：`user_progress_logger._transcript_kind` 对
  `channel=="evidence"` 一律归 `diagnostic`,不再落进 `final`;`TurnFinal` 去掉 `step.summary` 的 harness
  回退,主线程"回答"只取模型 `content_delta`。E2E:greet.py 回答=模型复盘,自证串消失。
- **切片 2a — 验证带真命令+输出（已做，验证）**：验证事件 `content_delta` = `✓/✗ $ <command>` + 首行输出;
  `NarrativeStep` 渲染。E2E:square.py 验证步显示 `✓ $ python -m pytest … / Test command passed`。
- **切片 2b — 工具卡是真实动作 + 内部脚手架下主线程（已做，验证）**：
  - `tool_execution_gateway._tool_action_label` 给 coder 工具事件一个**带真目标、且 call/result 一致**的标题
    (`写入 <path>` / `$ <command>`),前端按标题合并成**一张有实义的卡**。
  - harness 生命周期 `turn_start/tool_observation/turn_end`(`正在使用…`/`工具结果`)从 `main` **降级到
    `inspector`**——真实体已由 coder 工具卡承载,不再每个工具刷 3 张卡。
  - 前端 `narrative.ts`:用**稳定结构标记**(`runtime_event_type`/`tool_call_id`/`command`)区分真工具与
    内部标记;`执行迭代 N`/`任务执行进展`/`Worker action …` 及**已记录的**能力/权限决策(非 waiting)不再
    冒充显性工具卡,折叠进明细。默认视图 `focus→normal`(过程默认可见且干净)。
  - E2E(studio 起 run,isodd.py):`normal` 显性卡恰为 `写入 isodd.py`/`写入 test_isodd.py`/
    `$ python -m pytest …`/`$ python -c …` 四个真动作;权限决策/生命周期全部折叠;终答=模型真中文话;零英文。
- **切片 3 — 文档/上下文关联过程卡（已做，验证）**：
  - `runtime_profile_builder._record_profiles` 写 `context_mounts.jsonl` 后发 user_progress 事件
    (`transcript_kind=context_status`,复用既有枚举·无 schema 迁移,best-effort 不阻断挂载),标题
    "已关联任务上下文" + 中文文档清单(项目指南/目标简报/任务简报 + 产物/失败/决策/验证计数)。
  - 前端新增 narrative kind `context`(narrativeKind/label/icon=Paperclip),`ConversationTurn` 在
    工具卡上方**显性渲染**"上下文关联"卡。
  - E2E(studio 起 run·clamp.py):上下文卡显示"为本任务关联了：项目指南、目标简报、任务简报",
    置于 `写入/pytest` 工具卡之上;console 无错。
- **切片 4 — 阶段旁白降级为安静状态（暂缓·非显性问题）**:`理解目标/执行迭代/运行完成/开始验证/
  验证完成` 等阶段旁白经切片 2b 已**不再冒充显性卡**、仅存在于**默认折叠**的"详情"里(opt-in 明细,
  非显性展示问题)。进一步移出折叠需要:①可靠的稳定判据(试过的前端 fold 去噪对 runtime 事件行为不
  一致·仅删部分),或 ②在源头把这些 emit 的 `display_level` 降到 `inspector`——后者会触碰 DO_NOT_TOUCH
  的 `run_command.py`(`执行迭代/任务执行进展`),须单独谨慎处理。故留作后续专项,不在本刀草率降级。

## 主流实证

- **Claude Code**：主线程 = 模型流式文字 + `$ cmd` 及真实 stdout + diff;状态提示绑真实结果,无 harness 自证句。
- **Cursor / Copilot**：编辑即真实 diff,agent 消息是模型 prose;测试结果来自真实 runner。
- 三者皆无"harness 用 agent 口吻自报已完成/已验证"的旁白——这正是本 ADR 要删的东西。
