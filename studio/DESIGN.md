# Studio Design Philosophy

This document captures the UX principles that guide every Studio feature decision.  
Read this before adding any new UI element or changing how events are rendered.

---

## 1. The User's Mental Model

The user thinks in terms of **goals and results**, not agents and state machines.

They send a message: *"Refactor the auth module"*.  
They expect to receive: a readable answer about what happened.

Everything in between — planning, tool calls, model reasoning, repair loops — is **process**. The user may want to inspect it, but they should never be *forced* to wade through it to find the answer.

**Wrong mental model (what we had before):**
```
[思考 card]
[计划 card]
[工具调用 card]
[思考 card]
[工具调用 card]
[验证 card]
[最终结果 card]   ← buried at the bottom
```

**Right mental model:**
```
User: "Refactor the auth module"

[Live: 思考中… tokens stream in…]
[Live: ⚡ read_file  ✓ completed]
[Live: ⚡ write_file  ✓ 3 files changed]

→ collapses when done →

▶ 🔧 6步 · 思考 · 工具调用 · 验证     ← optional inspection

A Asteria
已完成 auth 模块重构。抽取了 AuthContext，
移除了 prop drilling，测试全部通过。
```

---

## 2. Streaming Is the Primary Experience

Long-running tasks can take 5–30 minutes. Users must never stare at a blank screen.

**While a turn is running, show:**
1. **Phase indicator** — where in the pipeline we are (思考中 / 规划中 / 执行工具 / 验证中)
2. **LLM token stream** — the model's actual words as they arrive, exactly like ChatGPT
3. **Tool chips** — each tool invocation appears inline as a small badge with status
4. **File change chips** — modified files appear as `📄 App.tsx +12 -3`
5. **Permission cards** — surface immediately when the runtime needs approval

**After the turn completes:**
1. Collapse the live view into a small badge (expandable for inspection)
2. Show the formal reply card prominently

This pattern is identical to how Claude Code, Codex, and Cursor show their work.

---

## 3. Conversation Turn Structure

Every user message creates one **ConversationTurn**. Turns stack vertically.

```
Turn N:
  [User bubble — right-aligned]
  [Running: LiveStream] OR [Done: process badge + reply card]

Turn N+1:
  [User bubble — right-aligned]
  ...
```

This enables **indefinitely long working sessions**: user sends goal, reads reply, sends next goal. Older turns stay visible and readable. The conversation is the audit log.

**Alignment convention:**
- User messages → right-aligned bubble (blue tint)
- Agent output → left-aligned card (dark tint, "A" avatar)

---

## 4. Hierarchy of Visibility

Not all information deserves equal prominence. Rank from most to least visible:

| Level | What | Where |
|---|---|---|
| **Primary** | Agent's formal reply | TurnFinal card — always shown |
| **Secondary** | Live process (while running) | LiveStream — collapses when done |
| **Tertiary** | Process archive | Collapsed badge — expand to inspect |
| **Inspector** | Raw events, telemetry, evidence | Inspector panel (right side) |

Never promote inspector-level content to primary without a strong reason.

---

## 5. The Runtime ↔ Studio Contract

Studio can only be as good as the events the Runtime emits. The contract:

### Model output
- `model_delta.content_delta` — stream every token; Studio renders it live
- `model_end.telemetry` — include `{input_tokens, output_tokens, latency_ms}`; Studio shows it in the reply header

### Tool calls
- `tool_start.command` — the full command array; Studio shows it as a chip label
- `tool_end.content_delta` — stdout/stderr; Studio can surface it inline
- `tool_end.file_changes` — array of `{path, additions, deletions}`; Studio shows file chips

### Final answers
- `final_answer.content_delta` — **the full human-readable conclusion in markdown**  
  This is what the user reads. One-line summaries are not acceptable here.  
  Include: what was done, key results, evidence pointers, next steps.

### Permissions
- `permission_request.job_id` — **always set**; Studio routes Allow/Deny by this ID

### Display filtering
- `display_level: "inspector"` — hides event from Thread, shows only in Inspector
- `display_level: "main"` or absent — shows in Thread

---

## 6. What We Don't Show

The Runtime's internal state machine (plan/execute/review phases, worker orchestration, agent sub-steps) is **not** shown as primary content. Users don't care which agent ran which sub-task.

**We show outcomes, not machinery:**

| Don't show | Show instead |
|---|---|
| "PlanAgent started" | "规划中…" (phase label) |
| "Worker 3 of 5 completed" | "⚡ run_tests ✓" (tool chip) |
| "ReviewAgent evaluating" | "验证中…" (phase label) |
| eval_report.json scores | Human summary in final_answer |

---

## 7. Planned Features (in priority order)

1. **Tool terminal output** — `tool_end.content_delta` rendered inline, expandable
2. **Inline file diffs** — git-style `+/-` view on file chips, click to expand
3. **Token / cost budget** — running total per session, configurable limits
4. **Git status panel** — branch, dirty files, recent commits; read-only
5. **Terminal pane** — passthrough for manual commands during a session
6. **Global settings UI** — workspace path, model routing, permission policy
7. **Multi-workspace** — switch between projects without restarting
8. **Run comparison** — side-by-side diff of two run outputs

---

## 8. Reference: Similar Tools

For visual design inspiration and UX pattern validation:

- **Claude Code** (Anthropic) — streaming terminal output, tool use inline
- **Codex** (OpenAI) — streaming model output, file change diff view
- **Cursor** — agent mode with inline edits and terminal panel
- **Devin** — long-running task timeline with step-by-step replay

Studio's differentiator: **local-first, no cloud dependency, full evidence trail**.
