# S88 — CLI 双 run 守卫：把 S87 的「同工作区单写者」落到跨进程

## 用户拍的板（2026-07-18）

「开始，顺便把 CLI 双 run 守卫也授权给你做」——显式授权动 DO_NOT_TOUCH 的
`run_command.py` / `execute_command.py`。本刀关掉 1.2.110 如实记下的残留洞。

## 残留洞是什么（S87 留下的）

S87 把守卫放在 Studio 的 `startRuntimeJob`（BFF 内存态）。它护不住：

1. **CLI vs CLI**：两个终端各 `asteria goal … --root 同一工作区` ⇒ 两个进程无锁直写。
2. **CLI vs Studio**：Studio 的 run 在跑，终端再起一个 CLI run ⇒ BFF 根本看不见它。

1.2.109 探针已证并发 run 落在两个不同 OS 进程 ⇒ 进程内 `RLock` 结构上拦不住，
唯一诚实的形状是**跨进程文件锁**。

## 形状

**OS 持有的非阻塞文件锁**（新模块 `core/workspace_writer_lock.py`）：

- 锁文件 `root/.asteria/locks/writer.lock`；Windows `msvcrt.locking(LK_NBLCK)`、
  POSIX `fcntl.flock(LOCK_EX|LOCK_NB)`。**锁随进程死亡自动释放** ⇒ 无需任何
  「陈旧锁破除」逻辑（PID 活性检查在 Windows 上有 `os.kill(pid,0)=TerminateProcess`
  的坑，整条路线绕开）。
- 占用者元数据写**旁文件** `writer.holder.json`（pid/command/goal/started_at），
  不写锁文件本身——Windows 区域锁是强制锁，写在锁文件里对手读不到。
  旁文件只在「抢锁失败」时被读，锁空闲时无人读它 ⇒ 崩溃残留无害。
- **进程内重入计数**（模块级注册表 + threading.Lock）：run→execute 嵌套、
  `_execute_until_no_ready` 循环里反复实例化 ExecuteCommand（run_command.py:1308
  记录过 pause 场景调两次）都不会自锁。
- 抢锁失败 ⇒ 抛 `WorkspaceBusyError`，消息点名占用者 + 明说「你的文件没有被动过」
  + 给下一步。cli.py 顶层 guard（cli.py:1712）把它转成无 traceback 的人话。

## 咽喉（进程内汇流已逐条追过，见调研）

| 咽喉 | 覆盖的 CLI 面 |
| --- | --- |
| `RunCommand.continue_run`（run_command.py:289，run() 三个返回点全汇流于此） | run / goal / `--continue-session` / resume（resume_command.py:183 直调 continue_run）/ supervised_goal_loop / **warm worker**（studio_worker.py 进程内调 RunCommand） |
| `ExecuteCommand.run`（execute_command.py:271） | execute / debug（debug_command.py:119 绕过 RunCommand 直入）＋ 兜底（重入计数下与上面共存） |
| `PromotionsCommand.run` 非 `list` 动作 | accept（accept_command.py:169 汇流）/ promotions approve·retry·reject·discard |

**白名单只读、其余全当写者**（S87 反向默认原则的 CLI 版）：chat/ask、plan、review、
status、`promotions list` 不碰锁。锁不放 `CandidateWorkspace.promote()`：
`_promote` 的 `except Exception`（promotions_command.py:180）会把拒绝吞成
mark_promotion_failed——拒绝必须发生在会被吞之前。

## 关键无自锁论据（调研结论，实现前提）

- 默认路径全进程内：LocalExecutor 纯进程内 `run_model_driven_turn`，自主环
  （repair/replan/goal-replan/续跑）全进程内，**execute 期间不 spawn 同 root 的
  asteria 子进程**。
- 唯一外部写者 `background start`（local_background_run.py:159 spawn CLI 子进程）：
  **父进程不持锁**（它不经三咽喉），子进程作为普通 run 自己抢锁 ⇒ 语义正好。
- warm worker 严格串行（studio_worker.py:22 自述），per-request 抢/放。

## 与 Studio 守卫的关系

双层，不冗余：BFF 层拦 Studio-vs-Studio（消息级、有线程内人话事件）；本层拦
CLI-vs-CLI、CLI-vs-Studio（进程级、CLI stderr 人话）。Studio 正常路径永远先被
BFF 拦，落到本层的只有「BFF 看不见的第二个入口」——这正是它的职责边界。

## 明确不做

- **不做排队**（同 S87：新持久状态+新机制，等真 friction 证据）。
- **不动 decide**：CLI `decide` 写的是 `.asteria` 决策记录，不直写用户文件；
  按最小刀原则不扩（若将来 decide 长出写用户文件的路径，反向默认不保护它——
  在锁模块 docstring 里如实记这条边界）。
- **不提供 env 关闭开关**：安全守卫做成可关等于没修（beta_safe 的教训）；
  真遇到锁不工作的文件系统再按证据开洞。

## 验收

1. **单测**（`tests/unit/test_workspace_writer_lock.py`）：同进程重入不自锁；
   **真子进程**持锁时父进程抢锁必败且消息点名（沿 test_local_background_run 的
   subprocess 先例）；释放后可再抢；holder.json 损坏时降级为通用消息不炸。
2. **探针**（scratchpad·真 CLI·零凭证）：两个终端语义各起一个 run 同一 root ⇒
   第二个 exit≠0 且 stderr 出现「另一个」与「没有被动过」；第一个不受影响。
3. **回归**：pytest 全量 + ruff + mypy。改动文件均 DO_NOT_TOUCH（已授权），
   不夹带无关重构。
