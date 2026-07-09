# server.mjs 拆分依赖图 + 执行顺序（Studio 前端工程质量债 #2）

> 用途：`studio/server.mjs` 巨石拆分的**下一阶段**规划底稿。本会话（2026-07-09）已抽完所有 0-风险叶子（②a–②e，server.mjs 5119→4419 行，`lib/` 现 6 模块）。剩余是**连通子图**，须按本图定的顺序整块搬，否则 `server.mjs ↔ lib/` 循环依赖。
>
> 关联记忆：[[studio-frontend-engineering-quality]]。已落地刀见该记忆②a–②e。
>
> **铁律（已在 6 刀验证）**：工厂注入 **live getter**（`workspace` 是 `let`，在 `openWorkspace`≈L4353 重新赋值——切库后按值捕获会指旧仓）；destructure 保调用点名；逐字节搬函数体；**每刀真起 server 端到端 smoke**（server.mjs 是 Node 运行时、不进 vite bundle，`build` 绿≠验证过）。

---

## 0. 关键发现：这不是"两块"，是"分层"

上会话以为剩下 = evidence 块 + chat 块两次切。依赖图证伪：两块**共享**同一批底层设施（事件总线 / job 注册表 / 几个广播纯工具）。共享层必须**先**独立出来，chat 与 evidence 才能干净落。硬把 chat 当单模块搬，会连 `appendEvent`/`liveJobs`/`sseClients`/`startRuntimeJob` 一起拖走，直接打碎 runtime-job 和 session 子系统。

分层（自底向上，每层是一刀或几刀）：

```
Layer 0  纯工具下沉（无状态·无 server-local 调用·多处共享）
         firstRuntimeText(40+ 调用) · readJson · readJsonlTail · latestDecisions
              │  下沉到中性 lib/，server 与上层都 import down，永不 sideways
              ▼
Layer 1  共享设施（有状态·被 chat 和 execute 同时用 → 必须先出来）
         event-bus.mjs : appendEvent + notifySSE + sseClients
         jobs.mjs      : liveJobs + pruneLiveJobs + 生命周期
              │
              ├──────────────┬───────────────────────┐
              ▼              ▼                        ▼
Layer 2  run-detail-reader   chat-answer            (execute 层暂不动)
         (evidence 只读)      (Tier 1 纯答案生成)      startRuntimeJob 等
              │                    │
              ▼                    ▼
Layer 3                     chat-routes.mjs (Tier 2 薄端点·最后)
```

---

## 1. Evidence 子图（19 函数连通分量）

seed→闭包 19 个：`readRunDetail, buildWorkerTree, buildPromotionPreview, enrichRuntimeProgress, workerSummaryForProgress, buildTranscriptRuntimeProgress, mainActionForRun, runtimeActionFor, runtimeActionByKind, permissionPreview, enrichRuntimeRequestDecision, permissionPreviewForRuntimeRequests, firstRuntimeText, userProgressToStudioEvent, userProgressToRunDetailEvent, latestDecisions, readJson, readJsonlTail, listRunEvidenceFiles`。

**只有 2 个 IMPURE（定义注入面）**：
- `readRunDetail`（L3412）读 `workspace`
- `runtimeActionByKind`（L761）读 `workspace, python, moduleName`

其余 17 个纯（只 in-set 调用 + 已有 lib import）。

**共享助手雷区**（被子图 *和* 无关代码同时调 → 移动会逼 server 反向 import lib）：
| 函数 | 定义 | 无关调用者 | 处置 |
|---|---|---|---|
| `firstRuntimeText` | 2728 | ~40（chat/status/plan/review） | **Layer 0：下沉 text-utils.mjs** |
| `readJson` / `readJsonlTail` | 4178/4186 | 15+ 通用 IO | **Layer 0：下沉新 `lib/run-io.mjs`** |
| `latestDecisions` | 720 | handleDecisionResolve/Answer, readChatContext | **Layer 0：下沉中性 util** |
| `userProgressToStudioEvent` | 3223 | tailUserProgress, startRuntimeJob, readRuntimeUserProgressEvents | 移则 server 反 import；或与 runtime-progress 层一起议 |
| `permissionPreview` | 898 | permissionPreviewForMode(域外) | 连 `permissionPreviewForMode` 一起移，或 server 反 import |

**Layer 2 提议模块 `lib/run-detail-reader.mjs`（工厂）**：
```js
export function createRunDetailReader({ getWorkspace, python, moduleName }) { … }
// 导出 readRunDetail, runtimeActionFor, runtimeActionByKind,
//      userProgressToStudioEvent, mainActionForRun, …
// redact/redactText/buildOrchestrationWorkflowMonitor/run-evidence-transforms.*/
// workspace-paths.* 直接 import，无需注入
```
**前置**：Layer 0 的 4 个纯工具必须先下沉，否则本模块与 server 侧发生 sideways import → 循环。

---

## 2. Chat 子系统（≈L397–2009 连续 + 2011–2047 + 2148–2189）

**判决：两层，不是一刀。**

### Tier 1 — 现在就能干净切：`lib/chat-answer.mjs`（≈L1406–2009 + 纯 builders 716–1176）
= `buildChatAnswer` + 全部文本/本地模板/status 助手族（strip*/repair/clean/isLikelyGarbled/localGeneral/localOutcomePlan/chatStatusAnswer/chatModelRouteAnswer/friendlyWorkflow/routeLabel/appendModelNotice/preferredChatRoute/chatHistoryForSession/extractVisibleChatAnswerFromEvents/fsSyncReadJsonl/requireReadFileSync/readChatContext/sideAskContextHint/commandFromStatus/chatModelAnswer）。

注入面小、几乎全只读（除经 `appendEvent` 外无 singleton 写）：
```
{ getWorkspace, sessionPath, runCommand, python, runtimeRoot, moduleName,
  chatBackend, appendEvent, appendChatModelStart, appendChatFallbackDelta,
  overview, readRunDetail, commandJson, readJsonlTail, modelRouteSummary,
  latestDecisions }
```
这是 ~1600 行里干净的 60%。**前置**：`appendEvent`/`readRunDetail`/`readJsonlTail`/`latestDecisions` 需先在 Layer 0/1/2 就位。

### Tier 2 — 缠死，最后做：`chat-routes.mjs`（薄端点）
`submitUserGoal, handleRuntimeAction, handleDecisionResolve/Answer, handlePermission, startChatJob, handleChatMode`。硬阻塞：
1. **`appendEvent`（3025）是共享事件总线**——融合 events.jsonl+session.json 持久化 + `notifySSE`/`sseClients`，`startRuntimeJob` 和 session 层同样在用。→ **先抽 `event-bus.mjs`**。
2. **`liveJobs`（61）是共享 job 注册表**——chat job、runtime job、`/jobs`+`/stop`、`openWorkspace` 切库守卫都扫它。→ **先抽 `jobs.mjs`**。
3. **`workspace`/`runtimeRoot` 是可变 `let`（L4353-4355 切库重赋）**——所有读它们的 chat 函数都要 `getWorkspace()`/`getRuntimeRoot()` getter（git L69/preview L80 已是此模式）。
4. **`startRuntimeJob`（2221）是通用 execute 驱动、非 chat**——chat 端点调它，故它是**注入依赖**，须与 execute 层一起抽、不跟 chat 走。

### Chat 拥有 vs 只读
- **OWN（跟着搬）**：`pendingJobs`(103)、`CONTINUABLE_STUDIO_PHASES`(1165)、全部 `CHAT_*` 常量、整个答案生成族。
- **只读/共享（注入或留下）**：`workspace`(可变)、`runtimeRoot`(可变)、`routeClient`、`liveJobs`、`sseClients`、`appendEvent`/`notifySSE`、session 生命周期、evidence readers、config consts。
- **误挂·必须留在共享层**：`startRuntimeJob, tailUserProgress, rememberJobRunId, applyAutonomyForTier, runtimeActionByKind, runtimeCommand, extractRunId, runArtifactRefs`（通用 execute/runtime-job 层，chat 只是**驱动**它）；`channelToEventType, userProgressToStudioEvent` 属 runtime-progress 层。

---

## 3. 推荐执行顺序（每步一刀或数刀·独立提交·真 smoke）

> **进度（2026-07-09 续会话，②f–②j 已提交在 origin 分支 claude/pensive-napier-f5b7ab）**：
> server.mjs 4419→**3468** 行；`lib/` 新增 run-io / event-bus / jobs / run-detail-reader 四模块。

1. ✅ **Layer 0 下沉纯工具**（②f `ef57166`）：`firstRuntimeText`→text-utils.mjs；`readJson`/`readJsonlTail`→`lib/run-io.mjs`；`latestDecisions`→run-evidence-transforms.mjs。
   - ✅ 顺带 §4 死代码（②g `a4c8426`）：删 resolveStudioExecutionRoute / modelRouteSummaryLine / latestRouteDecision（级联孤儿）。
2. ✅ **Layer 1a `event-bus.mjs`**（②h `3981542`）：`sseClients`+`notifySSE`+`appendEvent` 工厂，注入 `getWorkspace`/`sessionPath`。**已解锁 chat Tier 2 前置。**
3. ✅ **Layer 1b `jobs.mjs`**（②i `cce3e59`）：`liveJobs`+`pruneLiveJobs` 工厂（纯内存、无 workspace 捕获）。
4. ✅ **Layer 2 `run-detail-reader.mjs`**（②j `fd641f2`）：readRunDetail + 14 helper 的 evidence 工厂，注入 `getWorkspace`/`python`/`moduleName`；5 名反向 down-import 回 server。server.mjs 再瘦 ~730 行。
5. ⬜ **Layer 2 `chat-answer.mjs`**：Tier 1 干净块（依赖 Layer 0/1/2，均已就位）。注入面见 §2 Tier 1（~15 项，几乎全只读）。**下一刀。**
6. ⬜ **Layer 3 `chat-routes.mjs`**：Tier 2 薄端点（依赖前面全部到位）。

execute 层（`startRuntimeJob` 家族）本轮**不动**——它是另一条轴，缠着 runtime-progress，值单独规划。

---

## 4. 顺手清理（勘察中发现的死代码）
- `resolveStudioExecutionRoute`（1161）无调用者
- `modelRouteSummaryLine`（1993）无调用者

删前 grep 全仓确认（含 studio/scripts smoke、tests）无引用再删——符合"死代码大刀阔斧删"但先验证。

---

## 5. 验证脚本（每刀必跑）
```
cd studio
npm run lint            # 0 error 目标（warn 可留）
npm run format:check
npm run typecheck && npx vite build   # build 绿≠验证 server 行为
node --check server.mjs
node --check lib/<新模块>.mjs
# 端到端真 smoke（选与该刀相关的）：
node scripts/run-detail-smoke.mjs
node scripts/session-lifecycle-smoke.mjs
node scripts/git-changes-smoke.mjs
node scripts/preview-serve-smoke.mjs
# chat 相关刀还需跑 chat/decision/permission 相关 smoke（在 scripts/ grep chat/decision）
```
安全：每次 commit/push 前扫 staged diff 不含保护路径（`.env*`/`secrets/`/`*.pem`/`*.key`/`id_rsa`/`.git/`）与真密钥；仅用户明确要求才 push。
