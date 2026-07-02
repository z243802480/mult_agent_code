# S74 P3 桌面赌注落地（2026-07-02）

> 承接 `S74-full-system-claims-audit-20260702.md` §3 的 P3（裂缝④ 桌面级 table stakes / 前端诚实化）。
> 先派 6 代理钉当前代码（pull 到 498d31c + P1 b921028 + P2 36ac4c1 后）复核，并**严格分类**每项为
> honesty_fix / bugfix / new_feature + 冻结张力。原则：冻结内的诚实化/bugfix 直接做；**净新增能力/UI
> 即便审计称 table stakes，也须用户绿灯**（冻结「无 friction 证据的 Studio 新功能」+ 用户「要收敛不要加功能」）。

## 分类结论（6 项）

| 项 | 分类 | 冻结张力 | 处置 |
| --- | --- | --- | --- |
| P3-3 真流式去占位 | honesty_fix | 否 | 直接做（本批） |
| P3-6 事件 id 去重 | bugfix | 否 | 直接做（本批） |
| P3-5 parts 1-2 raw evidence | honesty_fix | 否 | 直接做（本批） |
| P3-2 Sidebar 文档超卖 | honesty_fix | 否 | 直接做（本批） |
| P3-1 Stop/中断 | new_feature | 是 | 用户绿灯 → 功能批 |
| P3-2 会话搜索框 UI | new_feature | 是 | 用户绿灯 → 功能批 |
| P3-4 token 用量面板 | new_feature | 是 | 用户绿灯 → 功能批（仅 token，无 USD） |
| P3-5 part 3 capability_decisions 面板 | new_feature | 是 | 用户绿灯 → 功能批 |

## 第一批：冻结内诚实化/bugfix（4 项，纯 studio + 1 文档，零后端代码、零 DO_NOT_TOUCH）

### P3-3 真流式被占位句遮蔽（honesty_fix, `studio/src/features/thread/LiveStream.tsx`）
- 根因：流式链路已端到端通（server 发真 model_delta → `narrative.toNarrativeEvents` 相位无关累加 content_delta →
  作为 step.events[0] 到 LiveStream），但 LiveStream 对 `phase!=='chat'` 用占位句「Putting together a plan…」
  **客户端主动丢弃**这份已在手的真实数据。
- 修法：删占位分支，所有相位统一渲染 `event.content_delta`。单文件、纯前端。

### P3-6 事件同步层 id 命名空间 + 回放去重（bugfix, `studio/server.mjs`）
- 根因：`userProgressToStudioEvent` 生成命名空间 id `runtime-<runId>-<upe>`，但两处 live-tail append
  （`tailUserProgress` + close 处理器）又用对象 spread 把 event_id 覆写回**裸 `upe-NNNN`**（per-run 计数器、仅 run 内唯一）。
  后果：(a) 跨 run 碰撞——前端 `mergeEventLists` 用整 session 一个扁平 id Set，run A 的 upe-0001 进集合后 run B 的
  upe-0001 被判重丢弃 → run B 早期事件在 UI 消失；(b) 同 run 回放双份——live-tail 裸-id 持久化副本与回放再读的命名空间-id
  副本，`mergeSessionAndRuntimeEvents` 只按 type 过滤 5 类（model_*/file_changed），tool_start/final_answer 等两份都留。
- 修法：删两处裸-id 覆写（让 `...mapped` 的命名空间 id 落盘）；`mergeSessionAndRuntimeEvents` 增按 event_id 去重
  （runtime 再读为权威，session 侧同 id 丢弃），含 legacy 裸-id 后缀等价兜底（`upe-NNNN` 视为任一 `*-upe-NNNN` 的重复）
  避免回放旧 session 双份。全部 studio 层。

### P3-5 parts 1-2 Inspector raw evidence（honesty_fix, `EvidenceExplorer.tsx` + `types.ts`）
- 根因：server 已把 `payload.mcp_invocations`/`skill_invocations` 组装进 run detail 并置 `inspector_raw_evidence_source`
  作为「给 raw evidence」的承诺，但前端 EvidenceExplorer 从不渲染二者；且 Run files 硬 `files.slice(0,6)` 静默丢弃、无计数。
- 修法：`types.ts` 补 `mcp_invocations?`/`skill_invocations?`；EvidenceExplorer 加两个 EvidenceBlock（mcp/skill，含 renderLine
  分支）渲染已组装数据（零 server 改）；Run files 去 `.slice(0,6)`，改显全量 + 表头计数。
- 残留（列入功能批）：capability_decisions.jsonl 有写无读（P3-5 part 3，须 server 加读 + 新 UI = new_feature）。

### P3-2 文档超卖（honesty_fix, `docs/zh/Asteria Studio 产品设计.md`）
- 根因：§2 line 38 把 Sidebar 列为 `Projects / Workspaces、Sessions、Search、Settings`，但代码只有 Sessions（all/recent 过滤）+ Settings。
- 修法：改为「Sessions（含 all/recent 过滤）、Settings（已实现）；Search / Projects / Workspaces 为规划中、当前尚未实现」。

### 第一批验证
- studio `tsc --noEmit` clean；`vite build` ok；`test_documentation_contracts` 22 passed；
  事件/流式 studio smoke **6/6**（run-detail / session-main-path-contract / chat-lifecycle / plan-output / chat-stream-final / intent-routing，其中 run-detail 直验事件合并去重）。
- 零后端 Python 代码改动；零 DO_NOT_TOUCH。

## 第二批：new_feature（用户绿灯，另见本报告后续追加 / 后续提交）
- P3-1 Stop/中断、P3-2 会话搜索框、P3-4 token 用量面板（仅 token，后端无 USD/单价，货币费用另立数据能力）、
  P3-5 part 3 capability_decisions 面板。用户拍板「合理的常见功能都要加上」→ 4 项均实现（token 面板诚实标注不含货币）。
