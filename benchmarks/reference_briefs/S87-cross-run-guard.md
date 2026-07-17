# S87 — 跨 run 守卫：同一工作区不许两个写者同时跑

## 用户拍的板（2026-07-17）

我把三件卡在用户的事按判断排了序，用户回「按你建议进行吧」——**修法也交给我定**。
本刀 = 第一件：修「跨 run 无守卫」这个**现存缺陷**（不是未来功能）。

## 缺陷是什么（探针已证·1.2.109）

同一个 workspace 上开两个会话各发一条指令 ⇒ **两个 run 都真的起来**，且落在**两个不同 OS 进程**：

- 暖 worker 就绪时 = 1 个暖 worker 进程 + 1 个冷 spawn（PID 844·`w.busy` fall-through）
- 暖 worker 未就绪时 = 2 个冷 spawn（PID 21296/6568·两条命令行 `--root` 同一个 workspace）

⇒ 进程内的 `_PROMOTION_APPLY_LOCK = RLock()`（`candidate_execution_gateway.py:17`）**结构上拦不住**，
而它的 docstring 声称防「concurrent run 交错写」——**那句注释在说谎**。

**Studio 所有会话强制共享一个 workspace**：`workspace` 是模块级单例（`server.mjs:50`），
只被 `openWorkspace` 全局改写。`createSession` 把它盖章进 `session.workspace`（`:1477`）但没人回读，
真正发起 run 时用的是全局值（暖路 `root: workspace`·`:1093`；冷路 `cwd: runtimeRoot`·`:1176`）。
⇒ 「两个会话指向同一路径」不是风险场景，**是默认且唯一的场景**。

## 本刀开工时纠正的一个我自己的错（重要）

1.2.108/1.2.109 把 **`promote()` 当成了写共享工作区的那条路**。**调研推翻了它**：

> **`promote()` 不是主路径。** 候选工作区隔离**只在**「一个 tool batch 里 ≥2 个 spawn_subagent
> 且含 writing expert 且 flag 打开」的并发分支才发生（`execute_command.py:1278-1288`）。
> **默认串行路径根本不建候选区**——模型的 `write_file` 经 `PathGuard(context.root)`
> （`tools/file_tools.py:55`）**直写 source_root**，`context.root` 就是 `--root` 传进来的那个。

⇒ 缺陷**比我记的更宽**：常见路径上连那个进程内的 `RLock` 都没有，是**完全无锁直写**。
⇒ 也说明**守卫不能只盯 `promote()`**——那会漏掉默认路径。本刀的守卫放在**起 run 之前**，
与写路径无关，天然覆盖两条分支。

## 守卫范围：哪些 mode 要拦（逐个追过控制流，不是 grep）

| mode | 能改用户文件 | 依据 |
| --- | --- | --- |
| `run` | **是** | 串行 `_spawn_subagent`（`execute_command.py:1259`）共享 context → `WriteFileTool` `PathGuard(context.root)` 直写（`tools/file_tools.py:55`）；并发分支另经 `promote()` |
| `continue` | **是** | 就是 `run --continue-session`（`server.mjs:630-646`） |
| `resume` | **是** | `resume_command.py:183` → `RunCommand`，同 run |
| `accept` | **是** | `accept_command.py:169` → `promotions_command.py:179` `candidate.promote()` → `shutil.copy2`；Studio 不传 `--no-promote`（`server.mjs:623`）⇒ **默认自动批准全部 pending** |
| `debug` | **是** | `debug_command.py:119` → `ExecuteCommand`。（`agents/debug_agent.py` 已删但**子命令还在**·`cli.py:2187`·`debug --help` exit=0 亲验） |
| `chat` | 否 | `chat_command.py:234` 只 `.names()` 喂 prompt envelope，无工具执行循环；CLI help 自述「no state-changing project work」 |
| `review` | 否 | 同样只 `.names()`（`review_command.py:178`）；`--rerun` 默认 off 且 Studio 不传（`:126`·`server.mjs:609`） |
| `plan` | 否 | 只 `.names()`（`plan_command.py:250`）；`cli.py:1772` 打印「read-only analysis; no execution started」 |
| `decide` | 否 | Studio 恒带 `--list-pending`（`server.mjs:625-626`），写前 early return（`decide_command.py:101-107`） |

**设计取向：反着列。** 白名单只读的 mode，**其余一律当写者**——将来新增一个 mode 会**默认被守卫**，
而不是默默漏防。失败方向选保守，是这仓库自己的教训（见 changelog 1.2.49 那批「乐观默认掩盖缺失」）。

## 形状

**拦截点 = `startRuntimeJob`（`server.mjs:1121`）** —— 唯一咽喉，6 个调用点全过它。
不放在 python 的 `PathGuard` 层：那是 per-process 的，跨进程要文件锁 = 更大的刀，且要动
DO_NOT_TOUCH 的 `run_command.py`/`execute_command.py`。

**拒绝要说得出话（不能静默）**：`requestJson`（`src/api.ts:20-24`）**只在 HTTP 非 2xx 时 throw**，
而 messages 路由恒发 200 ⇒ 若只返回 `{ok:false}`，前端会当成功、**用户的消息静默蒸发** = 拿一个 bug
换另一个 bug。故走**既有的「任务没起来」通道**（`server.mjs:1229-1239`：`type:"error"` + job 标 failed
+ 人话 title/summary）——从用户视角，这轮确实没开始。零前端改动。

**措辞要点名**：说清是**哪个会话**在占用、以及**怎么办**（等它跑完 / 去停掉它），不说「出错了」。

## 明确不做（本刀的边界）

- **不修 runtime 层**：CLI 直接起两个 run（两个终端）仍无守卫。那是更窄的场景（要用户刻意为之），
  且要动 DO_NOT_TOUCH。**如实记录残留洞，不假装修全了。**
- **不做排队**：把第二条消息排进跨会话队列 = 新的持久状态 + 新机制。既有 `composerQueue`
  （`src/session/composerQueue.ts`）是**per-session 前端队列**，排的是同一会话内的消息，不是这个语义。
  本刀先把**安全性**闭合；排队是体验优化，等真 friction 证据。
- **不碰 G19**：G19 是「让并行会话**安全**」（per-session worktree + 独立 source_root + 跨进程串行化）。
  本刀反而让 G19 的价值主张变清晰：**在 G19 之前，并行写 run 就是不安全的**，守卫把这件事从
  「静默损坏」变成「明说」。

## 顺带撞出（不在本刀修·另记）

**`orchestration` 是死路径**：`server.mjs:575-592` 构造 `python -m asteria_runtime orchestration run …`，
但 `cli.py` 的 subparser 全集里**没有 `orchestration``。亲验：exit=2 `argument command: invalid choice:
'orchestration'`，argparse 在任何副作用前就退出。⇒ 那段命令构造是坏的/死的。**本刀不动它**（无关改动），
但守卫的「未知 mode 当写者」默认会把它算成写者——无害（它本来就跑不起来）。

## 验收

1. **单测**（纯函数）：只读 mode 不被拦、不拦别人；写 mode 互拦；**未知 mode 当写者**（反向默认的回归）。
2. **探针**（真 BFF·零凭证·**用户真实路径**）：复用 1.2.109 那个 scratchpad 探针 —— 修前它证得
   `SAW_BOTH_RUNNING|true` + `MAX_RUNTIME_PROCESSES|2`；**修后必须变成 1 个 running + 1 个被拦**，
   且**被拦的那个会话线程上有一条说人话的事件**（不能静默）。
3. **回归**：`npm run test:ui`（先 build）+ vitest + smokes + eslint。
