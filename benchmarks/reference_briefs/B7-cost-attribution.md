# Slice B7 — 成本归属:谁花的钱(大重塑 Part B 前端拉齐 · 第四刀)

承 [B6](B6-model-todo-visibility.md)。B4 推迟清单第③条:"专家成本进汇总"。

## 开工前先证伪 —— 我自己的说法错了

我原本报给用户的是"**并发专家的开销不计入任何成本统计,数字会骗人**"。真跑一遍(fake 模型在真
`ExecuteCommand` 上派一个 coder 专家),**这个说法不成立**:

- `cost_report.model_calls = 5`,**专家那两次调用是算进去的**;token 也算了。**全局总数没骗人。**

**真缺口是归属,不是总数** —— 而且比我以为的严重:

| | 修前 | 真相 |
| --- | --- | --- |
| `cost_report.model_calls` | 5 | ✅ 对的(4 execute + 1 plan) |
| **worker 树 `total_model_calls`** | **0** | ❌ **跑了 5 次却报 0** |
| `model_calls.jsonl` 的 `task_id` | **字段不存在** | ❌ 5 条调用长得一模一样 |
| `workers.jsonl` 里的专家 | 无 | ❌ 只有主脑 |

**worker 树报 0 才是真正会骗人的数字**,而且它连主脑都漏了 —— 不只是专家。

## 根因(实测,不是推测)

`worker_runner._model_calls_for_runtime_profile` 按 **`runtime_profile_id` 匹配**来数一个任务花了几次
模型调用。而 `model_call_logger` 的字段**全部取自 `request.metadata`** —— 脊梁
(`model_driven_turn.py:197`)构造请求时 metadata 只有 `task_id / iteration / loop`,
**没有 `runtime_profile_id`** → 匹配不到任何一条 → 计为 0。

(FSM 时代填了这个字段,脊梁接管时没接上。归属信息在**源头**就丢了,不是汇总层的 bug。)

`runtime_context` 里**本来就有** `runtime_profile_id`(`runtime_profile_builder.py:153` 挂载时写入),
脊梁手上有这个值,只是没往下传。

## asteria_mapping(怎么做)

1. **`model_call` schema 加归属字段**:`task_id` / `subagent_role` / `worker_invocation_id`。
   ⚠️ **两份 schema 都要改**(`./schemas/` 运行时读 + `src/asteria_runtime/schemas/` 打包用)。
   顺带发现:**这两份本来就不同步**(30 vs 28 个属性)——记入 backlog,不在本刀范围。
2. **`model_call_logger` 持久化这三个字段**(metadata 里早就有 `task_id`,只是从没落盘)。
3. **`run_model_driven_turn` 加 `call_attribution` 参数**,合并进请求 metadata。
4. **`execute_command` 两个调用点传归属**:主脑从 `runtime_context` 取 profile/worker id;
   **子专家计到派它的那个任务的同一个 worker profile 上** —— 委派出去的调用**仍然是这个任务的开销**,
   worker 树才不会被拆碎;靠 `subagent_role` + child task_id 做逐专家归属,**不重复计数**。
5. **`SubagentRequest` 带 `call_attribution`**(放在 request 上而非另传参数,**云执行后端 stub 也要能
   照同样方式计费**)。
6. **专家结果卡带 `cost`**(model_calls / input_tokens / output_tokens),SubagentPanel 每行显示 token。
   *注意不要做冗余*:`iterations` 其实已等于调用次数(脊梁一轮一次调用),**真正新增的信息是 token**
   —— 一个专家可能只跑两轮却烧掉一个大上下文。

## Definition of Done(真跑验证,数字必须对得上)
- worker 树 `total_model_calls`:**0 → 4**;`cost_report` = 5(多的 1 次是 plan 的 goal_spec,不属于
  任何 worker)→ **一致,无重复计数**。
- 每条 execute 调用都可归属(`task_id` + `runtime_profile_id` 非空);专家的带 `subagent_role=coder`、
  主脑的不带。
- 专家结果卡 `cost = {model_calls: 2, input_tokens: 200, output_tokens: 400}`。
- pytest 全绿 + mypy 棘轮零新增债 + studio lint 0 error + build + 真 smoke。

## 后续
① 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary` / 重复内容浪费)
② 守门哑区(规划器给 prose 占位符而非路径时,续跑守门无从检查)
③ **两份 schema 已漂**(`./schemas/` vs `src/asteria_runtime/schemas/` 属性数不同)——需要一次对齐 + 防漂测试
④ 专家仍不进 `workers.jsonl`(worker 树里没有专家**节点**;本刀让专家的**开销**并入了派它的任务,
   但树形结构上专家还不是一个独立节点)——要不要做取决于是否需要树形下钻,不是数字正确性问题
