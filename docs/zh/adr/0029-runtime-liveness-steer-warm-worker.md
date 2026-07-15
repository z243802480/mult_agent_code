# ADR-0029 · Runtime 活起来 = 中途 steer(turn 边界注入)+ warm worker(消冷启)

- 状态：**Partially Accepted（2026-07-15）。机制②(warm worker) 已落地**（changelog 1.2.71·flag `ASTERIA_STUDIO_WARM_WORKER`·默认 OFF·冷路回落·studio_worker.py + server.mjs `finalizeRuntimeJob`/`dispatchWarmRun`·benchmark 均值 320ms/run 省·worker 4 单测 + 跨进程 wire 验）。**机制①(steer)仍 Proposed**——触 ADR-0016 认知环，**尚未获授权实现**。
- 关联：[[0016]] 认知归模型/边界归 harness · [[0027]] 软保险丝续跑环(同为 turn 边界护栏族) · 记忆 `low-burden-set-and-forget-ux` · `claude-code-parity-teardown`（前端对标拆解·#3 即时感物理天花板）· `mainarea-is-agent-loop-view`
- 授权：用户 2026-07-15 选「两条并行」= 授权**起草本提案**(纯文档)。**触环实现(机制①)待本 ADR 审定后单独授权**；warm worker(机制②)在环外，审定后即可落地。

## 背景

前端对标 Claude Code 的显示层差距（叙述去重 / diff 内联 / 即时感 / 工具输出内联 / 视觉对比度）已在 changelog 1.2.64–1.2.69 收掉。真正还「差一档」的两处，根都不在前端，而在 runtime 的**进程与交互模型**：

1. **中途无法真 steer。** 运行中用户打字，前端只能排队等整轮结束再发——`studio/src/components/Composer.tsx:117` 的注释诚实写着「我们从不假装 mid-step 注入，因为 runtime 兑现不了」，`composerQueue.ts` 是纯 `localStorage`、后端没有接收端。主流产品（Claude Code）你插一句、agent 下一个 turn 就改向。**当前架构下这不是前端偷懒，是后端没有中途输入通道。**

2. **首字延迟被 subprocess 冷启支配。** 每个 run 是一次全新 `python -m asteria_runtime run …` 冷启（`studio/server.mjs:778` 的 `spawn`），入口 `cli.py` 有 55 个顶层 import 拉起 ~50 个命令模块 / 235 个运行时 `.py`，每次都重建 model client、重读 `.asteria`——`server.mjs:524` 的 tail-poller 注释亦承认「subprocess cold-start still dominates」。#3 即时感把 BFF tail 节奏压到 ~313ms，但冷启那段动不了。

### 关键发现：turn 边界注入点已天然存在

执行脊梁 `run_model_driven_turn`（`src/asteria_runtime/core/model_driven_turn.py:108`）里，一个「turn」= `for iteration in range(1, max_iterations+1)`（`:165`）的一次 `模型→工具→观察` 循环。**iteration 顶部 `:166–178` 就是干净的 turn 边界**——注释即「上一批工具已跑完、下一次模型调用还没发出」，`pause_requested` 回调已挂在这里。更关键：**`:182–188` 的 `hook("turn_start")` 已经在做 `messages.append(ChatMessage(role="user", content=control.additional_context))`**——把一段补充上下文喂给模型下一次输入。**steer 指令走的就是这条现成的路，不新造机制。**

## 选项

### 机制①：中途 steer（触认知环）

- **选项 A（推荐）：文件驱动，照抄 pause 机制。** Studio/CLI 把用户指令写进 run 目录的 `steer.request`（多条 append）；`core/run_control.py` 加 `request_steer`/`take_steer`（读并清，与既有 `request_pause`/`pause_requested`/`clear_pause` 同构）；`model_driven_turn.py:166` 的 turn 边界读取 pending 指令、经既有 `messages.append(ChatMessage(role="user", …))` 注入。
  - 收益：与 pause 完全同构，爆炸半径最小；无需常驻进程即可工作（文件是进程间通道）；ADR-0016 上干净（见决策）。
  - 代价：只能 turn 边界生效、不能 mid-tool-batch——但这正是当前诚实边界，前端承诺从「立即」改成诚实的「下一轮生效」。
  - 风险：注入时机若在超长工具批期间，用户会感到延迟——由「下一轮生效」文案与 elapsed 计时（#3 已落）诚实披露。
- **选项 B：持久 socket/stdin 通道。** 依赖机制②的常驻 worker，走进程内消息队列。
  - 收益：可近实时投递、无文件轮询。
  - 代价：必须先有 warm worker；耦合两机制，风险叠加。**否决为首版**——文件通道先证明价值，socket 是后续优化。

### 机制②：warm worker（环外·进程生命周期）

- **选项 A（推荐首版）：单个常驻 worker，串行服务 run。** 用一个预热 Python 进程（import 已加载、model client 已建）常驻，`server.mjs` 不再每 run 冷 spawn，而是把 run 请求经 stdin/socket 投给它。
  - 收益：吃掉主导性的 import + client 冷启成本；改动全在 `server.mjs` + 新 worker 入口，**turn 循环一字不动**。
  - 代价：隔离弱于「每 run 全新进程」——一个 run 的全局态/泄漏会影响 worker。
  - 风险缓解：worker 每 run 重置工作态、model client 按 `(provider, workspace)` 键复用；跑满 N 个 run 或遇错即回收重建；`.asteria` 态本就落盘、天然跨 run 存活。
- **选项 B：worker 池并发。** 多 worker 并发服务多 run。
  - 收益：并发 run 也零冷启。
  - 代价：池管理 + 并发隔离复杂度。**推迟**——首版单 worker 串行已吃掉冷启主成本，并发是后续。

## 决策

采纳 **机制① 选项 A（文件驱动 steer）+ 机制② 选项 A（单 warm worker）**，**分阶段、按风险解耦落地**：

- **先落机制②（环外·可即授权）**：warm worker 不碰认知环，是纯进程生命周期改动，即时感收益立竿见影。**本 ADR 审定即可实现。**
- **后落机制①（触环·待单独授权）**：steer 修改 `model_driven_turn.py` 的锁定模块，必须先过下面的 ADR-0016 映射与合规清单，且**需用户对「触环」单独点头**后才动代码。

### 机制① 的 ADR-0016 三分类映射（触环改动必须自证）

| 元素 | 分类 | 处置 |
|---|---|---|
| 「用户中途说的这句话要怎么改变计划/动作」 | §1 认知 | **归模型**——注入的是用户原话作为一条 user-turn 补充上下文，模型自己决定如何采纳；harness 不解析、不转成 `next_action`、不强制工具调用 |
| 「何时把这句话交给模型」 | §2 边界 | **归 harness**——只在 turn 边界（`:166`）投递，绝不 mid-tool-batch；与 pause 同一投递语义 |
| steer 指令的读取/清除/排序 | §2 边界 | `core/run_control.py` 文件助手（读并清·多条按序 drain·与 pause 同构） |
| steer 可能把动作引向高危 shell/deploy/push | §2 边界（既有硬 guard） | **不新增放松**——steer 只加上下文，后续高危动作仍撞常开硬 guard；steer 本身无需新审批门 |
| budget / max_rounds | §2 保险丝（不变） | steer 不重置预算、不重置软轮次——正交于 [[0027]]；若 run 已结束则走既有 queue-for-after（自动续跑/新 turn） |

**合规清单（触机制①的改动必须逐条过）**：
1. 注入内容 = 用户原话，`role="user"`，**不做意图解析、不合成 `next_action`**——认知留给模型。
2. 只在 turn 边界读取注入，**绝不 mid-tool-batch**（与 Composer:117 的诚实边界一致）；前端文案改「下一轮生效」不许写「立即」。
3. 走既有 `messages.append(ChatMessage(...))` 路径（`turn_start` hook 同款），不新造注入机制。
4. steer 文件读并清 + 多条按序 drain，用 run 目录文件（跨进程通道），**不落 task_plan/schema**（避开双份陷阱·记忆 `schema-dir-runtime-vs-packaged`）。
5. 不触碰 pause/budget/replan 任何既有分支——steer 与它们正交，只多一次边界读取。
6. Studio 侧 steer 提交**无 `requiresPermission`**（用户自己的话不该拦自己）；但引出的高危动作仍走既有 guard，一字不改。
7. flag 默认可逐字节回退：关 flag = 今日行为（运行中排队、run 后发）。

### 明确不做（non-goals）

- 不做 mid-tool-batch 抢占（runtime 兑现不了，也违背 turn 边界语义）。
- 不让 harness 解析 steer 语义或据此改 goal_spec / 重分解任务（认知归模型；改 goal 仍冻结）。
- warm worker 首版不做并发池、不做 cloud VM（后者仍冻结）。
- 不碰北极星 / swarm / parallel_writes 全局默认。

## 后果

- 正面：即时感获得**两段**改善——warm worker 消掉冷启（首字从「冷启+首事件」变「仅首事件」）；steer 让「批处理 submit-and-watch」变「可中途改向的对话」，补齐对标 Claude Code 最深的一档。前端 Composer 的诚实排队可升级为「有活进程→现在插话(下一轮生效)/无活进程→排队 run 后发」。
- 负面/风险：warm worker 削弱进程隔离（缓解=按 workspace 键复用 client + 遇错/满 N 回收）；steer 触锁定模块（缓解=最小 diff + 合规清单 + flag 回退）。
- 迁移/验证要求：机制② 需一个 warm-worker 冷启对照 benchmark（同任务 冷 spawn vs warm 首字延迟）；机制① 需一个真栈 steer smoke（run 中写 `steer.request` → 断言下一 turn 的 messages 含该 user 消息且模型响应改向）。二者都在 flag 后、默认可回退。

## 回滚或替代条件

- 机制②：`server.mjs` 退回每 run 冷 spawn 即天然回滚。若 warm worker 出现跨 run 状态泄漏导致可测正确性下降（Golden-Task eval），关 warm 模式退冷启。
- 机制①：steer flag 关 = 今日行为（排队 run 后发）。若真栈观察到 steer 注入使模型跑偏 / 与 pause·budget 边界打架，关 flag 退回纯排队。
- 替代条件：若未来 runtime 改为常驻 + 支持进程内消息，机制① 可从文件通道升级为选项 B 的 socket 通道（另开 ADR）。
