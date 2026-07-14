# Slice B4 — 专家集群可见性(大重塑 Part B 前端拉齐 · 第一刀)

大重塑 Part B。后端已把「模型自发派子专家并发干活」翻成**全局默认**(ADR-0023 · §16 v1.2.33),
并在真 glm+minimax 栈证过(B1 brief)。本刀把这件事在 Studio 里**如实显性化**。

## 开工前测绘的诚实更正(别修不存在的问题)

子代理测绘 + 逐点核实后,推翻了两个想当然:

1. **主线程不是看不见子专家。** dispatch / result / merge-gate 三张卡后端**本来就带人话 title 且
   `display_level="main"`**(`execute_command.py:906/947/1080`),前端也早有 `subagent` step kind、
   Users 图标、常驻详情卡,Inspector 有 `SubagentPanel` 读的是**新证据**(`subagent_role/phase`)。
   `runtimeNarrative.ts:264` 那句 "后台执行中" 只是 **title 为空时的兜底**,实际不命中。
2. **B2「上下文压缩」没有"压缩前后 token"这种字段**(1.2.24 明记 honest defer)。
   任何"压缩了 X→Y token"的 UI 都会是**编造**。本刀不碰。

## 真缺口(核实过,有 file:line)

**① 并发本身不在证据里 —— 这是后端缺口,不是前端缺口。**
`concurrent_batch` 在 `src/` 与 `studio/` **全仓不存在**;它是 smoke 脚本
[自己从卡片顺序猜的](../../scripts/concurrent_experts_smoke.py)(`:200-203`,前两张是不是连着两个
dispatch)。运行时**从未记录**"这 N 个专家是一个并发批"。
→ 用户在主区看到两张"委派 coder 专家"卡,**没有任何东西说它们是同时跑的**。而这正是整个重塑的
头号能力,还刚翻成默认。前端若要显示"并行",只能复制那套脆弱的顺序启发式 = **把猜测当事实,不行**。

**② 子专家改了哪些文件 / 用哪个档位 / 哪个后端,后端拿到了但没写进卡。**
`SubagentOutcome.data{role, backend, changed_files}`(`core/worker_executor.py:99-103`)、
`ExpertProfile.model_tier/read_only`——result 卡的 `data` 只有 `role/iterations/ok/child_status`
(`execute_command.py:958-967`)。

**③ merge gate 的风险明细有 reader、无消费者(纯前端,零后端改动)。**
`merge_gate_dry_runs.jsonl` server 端**已读**(`studio/lib/run-detail-reader.mjs:821`),
`promotion_preview` 已含 `risky_files`/`risk_level`。但 `SubagentPanel` 的 merge banner 只显示
`promoted_files` 计数。

## observed_pattern(行业已验证)

- **Claude Code Task 工具**:并行子代理在主线程收成**一张卡**("Running 2 agents in parallel"),
  每个子代理一行(role + 状态 + 产出),子代理自己的过程**不刷主线程**、只回摘要。
  我们的 `_record_model_driven_event` 已按此设计(子事件 `display_level="inspector"`,
  `execute_command.py:1536`)——**对的,不动**;差的只是"这 N 个是一批、并行"这层归组。
- **Cursor / Windsurf**:并行编辑经"合并/冲突"面板收口,冲突要给出**是哪些文件**冲突,而不是只报数。

## asteria_mapping(怎么做)

**Triage Lock 边界(必须先钉死)**:`execute_command.py` 是 DO_NOT_TOUCH,但锁的原文是
"No refactor: execute_command.py …(**append user_progress only**)"(AGENTS.md §3)。
本刀在 `_record_progress` 的 `data={...}` 里**追加字段**,正落在这条明文豁免里 —— **不重构、不改控制流**。

### 后端(additive,~30 行)
- 批身份:照抄既有确定性计数器约定(`subagent_counter` + lock → `f"{task_id}-sub-{n:02d}"`,
  `execute_command.py:852-855`),加 `batch_counter` → `batch_id = f"{task_id}-batch-{n:02d}"`。**不用 uuid。**
- `_spawn_subagent` / `_run_child` 加可选 kwarg `batch: dict | None`,由三条派发路径注入:
  - 串行(`_spawn_batch:1152/1166`)→ `None`(**卡片逐字节不变**,老行为零回归)
  - B1-a 只读扇出(`:1157-1163`)→ `{batch_id, batch_size, batch_index, concurrent: True, batch_mode: "readonly_fanout"}`
  - B1-b 隔离写(`_spawn_isolated_writes`)→ 同上,`batch_mode: "isolated_writes"`
- dispatch/result 卡 `data` 追加上述批字段;result 卡再追加 `changed_files` / `model_tier` /
  `backend` / `read_only`(来源 `SubagentOutcome.data` + `ExpertProfile`)。
- merge-gate 卡 `data` 追加 `batch_id`(把合并结果绑回它那一批)。

### 前端(开工中修正了两处原设想 —— 见下)
- **主线程**:**一位专家仍是一张卡**(不合卡),同批的卡打一枚"并行 · N 位专家"chip。
  - *原设想是把同 `batch_id` 的卡收成一张。放弃的理由*:合卡会把每位专家的产出摘要/改动文件压成
    一行,信息反而变少;且 Claude Code 的并行 Task 也是**各自一张卡**同时在跑,合成一张才是自创设计。
    真正缺的从来不是"归组",是**并行这个信号本身**。chip 用既有 `capabilityChip` 族,不新造结构。
  - `batch` 缺失 = 串行 = **不打 chip**(vitest 锁死:串行不得声称并行)。
- **SubagentPanel**:每行补 `changed_files` / `model_tier` / 并行标记。
  - *原设想还要给 merge banner 补 `risky_files`/`risk_level`。核实后取消*:banner **本来就渲染
    `reconciliation.summary` 全文**,而后端阻止时那句话里已经带着冲突文件名(测绘报告说它"只显示
    promoted_files 计数"是错的)。反倒查出 `promotedFiles` 是**解析了从不渲染的死字段**(数量在
    summary 文本里已有)→ 删。要读 `promotion_preview` 得把 runDetail 一路 prop-drill 进面板,
    而 prop-drilling 本就是这个前端的已知债,不该为一条冗余信息再加一笔。

### 诚实边界(不做)
`model_todos.json`、`runtime_hooks.jsonl`、`context_budget_snapshots.jsonl` 三条证据线
**server 端根本没有 reader**,专家也不进 `workers.jsonl`(成本汇总天然漏专家)。
这四项各要新开 reader + 新面,是**另外的量**,本刀不碰 —— 见「后续」。

## Definition of Done

- 真栈(或 `scripts/concurrent_experts_smoke.py` 的 disjoint/readonly 模式)跑出的 run,
  `user_progress.jsonl` 的 dispatch/result 卡**真的带 `batch_id`+`concurrent`**;
  smoke 不再需要靠卡序猜并发(**判据从启发式升级为读字段**)。
- Studio 主区把同批 N 位专家显示成一张"并行"卡;串行 run 形态不变。
- SubagentPanel 显示每位专家改的文件 + merge 风险明细。
- pytest 全绿;studio lint 0 error + 真 smoke 端到端。

## 后续(诚实推迟,单独成刀)
① 模型自组织的 todo(`model_todos.json` / `runtime_progress.todo`——前端零引用)
② 护栏 hook 干预(`runtime_hooks.jsonl`——"模型为什么又多跑了几轮")
③ 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary`/重复浪费)
④ 专家成本进汇总(需后端让 child 也过 `worker_recorder`)
