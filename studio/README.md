# Asteria Studio

Local web control surface for **Asteria Runtime OS**.  
Studio's job: make every step of a long-running autonomous task visible, interactive, and easy to act on.

---

## Design Philosophy

Studio is built around one insight: **users don't care about internal agent states — they care about their task progressing**.

The Asteria Runtime is a state machine that coordinates multiple agents (plan → execute → review → resume). Studio's role is to translate that machinery into a legible conversation:

```
User sends goal
  └─ Asteria acknowledges and starts working
       ├─ [LIVE] LLM tokens stream in token by token
       ├─ [LIVE] Tool calls appear as inline chips (command name + status)
       ├─ [LIVE] File changes appear as chips (+12 -3 src/App.tsx)
       ├─ [LIVE] Permission requests surface immediately (Allow / Deny)
       └─ [DONE] Process collapses → Formal reply shown prominently
User reads reply and sends next goal
```

### Streaming-First

While a turn is running, the Thread shows a **LiveStream view**:
- Model tokens rendered as they arrive (exactly like ChatGPT/Claude)
- Tool invocations as small chips inline (`⚡ command_name  ✓ completed`)
- File modifications as change chips (`📄 App.tsx +12 -3`)
- Phase indicator (`思考中` / `规划中` / `执行工具` / `验证中`)

When the final answer lands, the live view collapses into a small **process badge** and the formal reply card appears. Users can expand the badge at any time to inspect every step.

### Conversation Structure

Every user message starts a **ConversationTurn**:

```
┌─ User bubble (right-aligned) ──────────────────────────────┐
│  "帮我重构 App.tsx 的状态管理"             18:42           │
└────────────────────────────────────────────────────────────┘

▶ 🔧 8步 · 思考 · 规划 · 工具调用 · 验证       ← collapsed archive

┌─ A Asteria  zai/glm-4.7  2,341 tokens ────────────────────┐
│  ## 结果                                                   │
│  已将 useState 重构为 useReducer...                        │
└────────────────────────────────────────────────────────────┘
```

This pattern supports indefinitely long working sessions: each goal produces one turn, turns stack vertically, older turns stay readable.

### UI alignment (Claude Code / Codex, 2026-06)

| Pattern | Source | Asteria Studio |
| --- | --- | --- |
| Per-turn file chips with +/- | Claude Code `/diff`, VS Code extension | Thread `FileChangeChips` → Inspector diff |
| Turn-scoped diff tabs (T1/T2/Current) | Claude `/diff` turn views | Inspector **Diff review** + Thread **Tn diff**（**T1=最新一轮**） |
| Unified diff line numbers + coloring | CLI diff TUI | **`DiffPreview`** in Inspector |
| Primary project folder (cwd) | Claude Desktop project picker | Workspace switcher + top-bar chip |
| Phase strip (Plan → Execute → Verify) | Codex/Cursor task workflows | `WorkflowPhaseStrip` under header |
| Git working tree review | Claude `/diff` Current view | Inspector **Workspace changes** panel |
| Accept/review after verify | Codex review workflow | Runtime snapshot + 审查/接受 buttons |

Click any **file chip** in the live stream or collapsed turn to open git diff (falls back to file preview for untracked files).

### What Studio Does NOT Show By Default

- Internal agent sub-steps (those are in the collapsed process archive)
- Raw JSON events (those are in the Inspector panel)
- Model routing decisions (Inspector → Model Routes)
- Worker result internals (Inspector → Evidence Explorer)

---

## Features

| Area | Status |
|---|---|
| Streaming LLM output (token-by-token) | ✅ |
| Tool call chips with command + status | ✅ |
| File change chips with +/- counts | ✅ |
| Permission cards (Allow / Deny inline) | ✅ |
| Conversation turn structure | ✅ |
| Process archive (collapsed, expandable) | ✅ |
| Model + token metadata on reply | ✅ |
| Session management (create, switch) | ✅ |
| Mode selector (chat / plan / run / review / resume) | ✅ |
| Chat mode (instant local reply, no CLI) | ✅ |
| Inspector panel (event detail, evidence, files) | ✅ |
| Evidence Explorer | ✅ |
| Model route viewer | ✅ |
| Workspace file list | ✅ |
| **Workspace switcher (open folder / recent)** | ✅ |
| **Primary cwd chip + project profile (init/git/AGENTS.md)** | ✅ |
| **Git workspace changes + diff preview** | ✅ |
| **Thread file-change chips → diff** | ✅ |
| **Turn diff tabs (Current / T1 / T2…)** | ✅ |
| **Workflow phase strip (Plan/Execute/Verify)** | ✅ |
| Token / cost limits display | 🔲 planned |
| File diff viewer (inline git-style) | ✅ Thread chips + Inspector preview |
| Git integration (changed files, branch status) | ✅ read-only status + diff |
| Terminal output panel | 🔲 planned |
| Global settings UI | 🔲 planned |
| Side-by-side diff toggle | Desktop diff pane | ✅ Unified / Split |
| Session Ctrl+Tab switch | Desktop parallel sessions | ✅ |
| Session rename + goal preview | Desktop session list | ✅ |
| Context category breakdown (`/context`) | CLI `/context` | ✅ Thread + Inspector |
| Staged / Unstaged diff tabs | git diff vs cached | ✅ |
| Accept/reject single file | CLI y/n/e | ✅ Stage / Discard (git) |

**对标计划**：[`docs/zh/plans/STUDIO_CLAUDE_CODE_PARITY.md`](../docs/zh/plans/STUDIO_CLAUDE_CODE_PARITY.md) · **视觉校准**：[`benchmarks/reference_briefs/S46-studio-visual-calibration.md`](../benchmarks/reference_briefs/S46-studio-visual-calibration.md)

---

## Runtime Output Contract

Studio depends on the Runtime emitting the right event fields. For the best experience:

### `model_delta` events
```json
{
  "type": "model_delta",
  "phase": "plan | execute | review",
  "model_provider": "zai",
  "model_name": "glm-4.7",
  "content_delta": "<tokens as they stream>",
  "telemetry": { "input_tokens": 800, "output_tokens": 434, "latency_ms": 2500 }
}
```

### `tool_start` / `tool_end` events
```json
{
  "type": "tool_start",
  "title": "Run tests",
  "command": ["python", "-m", "pytest", "tests/"],
  "status": "running"
}
```
```json
{
  "type": "tool_end",
  "status": "completed",
  "content_delta": "<stdout / stderr output>",
  "file_changes": [
    { "path": "src/App.tsx", "additions": 12, "deletions": 3 }
  ]
}
```

> **Key principle**: `content_delta` on tool events carries stdout/stderr so Studio can surface it inline. Populate it for every tool that produces terminal output.

### `final_answer` events
```json
{
  "type": "final_answer",
  "content_delta": "<full human-readable conclusion in markdown>",
  "artifact_refs": ["run-20260521-0001/final_report.md"],
  "evidence_refs": ["run-20260521-0001/eval_report.json"]
}
```

> **Key principle**: `content_delta` must contain the actual conclusion — the plan, the execution summary, the review verdict. Studio renders this as the reply card. A one-line summary here means a useless reply card.

### `permission_request` events
```json
{
  "type": "permission_request",
  "job_id": "pending-1716234567-a3f2b1",
  "title": "需要权限确认",
  "command": ["python", "-m", "asteria_runtime", "run", ...],
  "status": "waiting_user"
}
```

> **Key principle**: `job_id` must always be set. Studio uses it to route the user's Allow/Deny response back to the correct pending job.

---

## Start

```powershell
cd studio
npm install

# API + UI together
npm run start:studio

# Or separately:
npm run server -- --workspace F:\mult_agent_code
npm run dev
```

Open: `http://127.0.0.1:5174`

## Build

```powershell
npm run typecheck
npm run build
# Static UI served by API server on port 8787
npm run server -- --workspace F:\mult_agent_code
```

---

## Architecture

```
studio/
├── server.mjs          # Node.js API adapter (port 8787)
│   ├── SSE event stream (/api/studio/sessions/:id/events/stream)
│   ├── Permission routing (job_id → pending job map)
│   ├── Chat mode (instant replies, no CLI)
│   └── Final text extraction (reads .asteria/ run artifacts)
│
└── src/
    ├── App.tsx                 # Root: session state, event subscription
    ├── api.ts                  # Typed API client + SSE subscription
    ├── narrative.ts            # Event → NarrativeStep → RunNarrative
    ├── types.ts                # Shared types (StudioEvent, NarrativeStep…)
    └── components/
        ├── Thread.tsx          # Conversation turns (LiveStream + TurnFinal)
        ├── NarrativeStep.tsx   # Individual step card (for process archive)
        ├── EventCard.tsx       # Raw event card (Inspector)
        ├── Composer.tsx        # Message input + mode selector
        ├── Inspector.tsx       # Right panel: event detail, evidence, files
        ├── PermissionCard.tsx  # Allow / Deny inline card
        ├── Sidebar.tsx         # Session list + system status
        └── Shared.tsx          # Status badge, Metric tile, Banner
```

### Event flow

```
Python Runtime
  └─ UserProgressLogger.record()  →  user_progress.jsonl
       ↑ tool calls, model output,
         permissions, conclusions

server.mjs
  └─ tailUserProgress()  →  SSE stream  →  browser EventSource
  └─ appendEvent()       →  session events store (JSONL)

App.tsx
  └─ subscribeToEvents()  →  mergeEvents()  →  React state

narrative.ts
  └─ toNarrativeEvents()    (merge streaming model chunks)
  └─ buildRunNarrative()    (group into NarrativeSteps)
  └─ splitIntoTurns()       (one turn per user message)

Thread.tsx
  └─ ConversationTurn
       ├─ turnRunning → LiveStream   (tokens + chips)
       └─ done        → TurnMiddle + TurnFinal
```
