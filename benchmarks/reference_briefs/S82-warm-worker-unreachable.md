# S82 · warm worker 从出生起不可达 + 权限档按数据穿透

## 缘起

做 G8（模型选择器）时追 `model_strategy` 的接线路径，撞见的。不是计划中的活。

## 探针证据（不是读代码读出来的）

真 BFF（`server.mjs`）+ 真路由（`POST /api/studio/sessions/:id/messages`）+ fake provider（零模型开销），
临时在 `startRuntimeJob` 的暖路分支前插一行日志：

```
warm worker boot line: ENABLED
PROBE|mode=run|warmEnabled=true|commandOverride=TRUTHY|warmBranch=false
VERDICT: warm branch NEVER taken (dead code)
```

warm worker 确实启用、确实预热、确实占着一个进程——**暖路一次都没进过**。

## 根因

`server.mjs:1097` 的守卫是 `WARM_WORKER_ENABLED && !commandOverride && (mode === "run" || "goal")`。

`startRuntimeJob` 的 **6 个调用点全部传了非空 command 数组**（`chat-routes.mjs:248/303/368/434/818`、
`server.mjs:1289`）⇒ `!commandOverride` **恒为假** ⇒ `dispatchWarmRun` 永远不被调用。

时间线（`git log -S` 自证）：

- `ae3e358`（**2026-07-14**）server.mjs 拆分收官 → chat-routes 抽到 lib/，从此**总是**传 command
- `f08111a`（**2026-07-15**）warm worker 落地，守卫写成 `!commandOverride`

**拆分在前。** 我加暖路时那个"总是传 command"已经在仓库里躺了一天 ⇒ **生下来就是死的**，
从没处理过任何一个 run。

## 记录与实际的分歧（本条的诚实账）

changelog **1.2.75** 写的是「warm worker **翻默认 ON**·冷启均值 **320ms/run 省**·**真栈 E2E 验**」。

- 「机制是真的、是快的」——**成立**（worker 本身能跑，wire 协议对）
- 「真栈 E2E 验」——**验的是 worker 的 wire 协议，不是集成**。测试直接喂 worker 请求，
  没走 `startRuntimeJob`，所以看不见守卫把它挡在门外
- 「320ms/run 省」——**从未兑现过一次**

⇒ 属「说谎审计」bug class：**验了组件，声称了系统**。子型待定（与 f 压缩式虚构不同：
这条不是虚构，是**验证范围被误报成更大**）。

## 那个守卫歪打正着挡住的第二个 bug（关键·别踩）

`dispatchWarmRun` 构造的 request（`server.mjs:1039-1050`）**没有 `permission_level`**
⇒ `studio_worker.py:112` 吃默认 `"balanced"`。

而冷路的档位是**以 CLI flag 形式**带的（`chat-routes.mjs:220-223` 的
`withPermissionLevel(cmd, mapPermissionLevel(permissionMode))`）。

⇒ **谁"顺手把暖路修通"，用户选的权限档就会被静默降级成 balanced**：`ask_everything` 的 run
会被升成自主档（三环 + auto-accept 全开）。这正是记忆 `permission-mode-two-sources-of-truth`
那条 bug 的复发形态。

**所以修法必须是「参数按数据穿透」，不能靠解析 CLI flag。**

## 等价性核实（复活一条从没跑过的路径的前提）

`studio_worker._handle_run`（`:103-115`）与 `cli.py`（`:2013-2029`）的 `RunCommand` 构造**逐字段对齐**：
root / goal / run_id / max_iterations / max_tasks_per_iteration / enable_research / parallel_writes /
mode="goal" / permission_level / model_strategy / continue_session。

CLI 多出的 `input_roots` / `output_root` / `artifact_root` / `worktree_policy`：Studio 的
`runtimeCommand("run", goal)`（`server.mjs:542-556`）**根本不传这些 flag** ⇒ 两边都吃同样的默认。

⇒ 暖路对 Studio 场景是忠实的，**唯一的缺口就是 permission_level**（`model_strategy` 两边今天
都吃 "auto"，故非回归——它是 G8 那刀的活）。

## DoD

1. 暖路对普通 run/goal **真的可达**（探针复验：`warmBranch=true` 且 `job.warm === true`）
2. 用户选的权限档**在暖路上不丢**——冷路与暖路对同一个 tier 得出同一个 level（测试钉死）
3. 自定义命令（resume/continue/review/accept/decide/follow-up）**仍走冷路**（暖路只认 plain run）
4. worker 不可用/忙/崩 → 透明回落冷 spawn（既有行为不动）
5. 1.2.75 的记录就地纠正（**不是追加**——追加=子型 d）

## 非目标

- `model_strategy` 穿透 = **G8 那刀**（本刀不夹带；今天两路都是 "auto"，无回归）
- 不改 worker 的 serve loop / 不改 wire 协议形状（只加字段）
- 不动冷路的 CLI flag 形式（它是对的，且 CLI 自己也在用）

## 反面教训（写给下一个我）

**"翻默认 ON" 之前必须验的是「用户的真实路径会不会走到它」，不是「它自己能不能跑」。**
组件级 E2E 绿 ≠ 机制上线。这条如果当初拿真 BFF 发一个真消息看一眼 `job.warm`，
当场就露馅了——而我写的是 wire 测。
