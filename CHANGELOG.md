# Changelog

All notable changes to asteria-runtime. This project targets a first releasable
version (v0.2-alpha); entries are distilled from git history, not narrated.

## [Unreleased]

### Studio — front-end productization (S76 · iterations I1–I14 across 5 goal-driven rounds)

A competitor-benchmarked (Claude Code / Cursor / Cline / Zed / Windsurf / Codex /
Aider) redesign of the Studio main content area and long-task robustness. Plan:
`docs/zh/前端产品化路线.md`. Highlights beyond the iteration-1 liveness fix below:

- **Rich, honest main content area.** A sticky "spine" per run — phase strip
  (understand→plan→execute→review→done, lit only to the phase actually reached) +
  a live plan/todo checklist derived from the real `task_plan` (○◐✓⚠, "N of M",
  nothing when there is no plan) + a context/token meter from `cost_report`
  ("N% context · used/window · in/out (est.)", amber past 0.75, never a `$`).
- **Reasoning cleanup** centralized (`cleanReasoning` strips stray `<think>` on every
  render path) + a live streaming caret.
- **Honest transport + errors.** Send/decision failures now toast with Retry instead
  of failing silent; a `live/reconnecting/offline` connectivity pill with SSE
  exponential-backoff reconnection; unknown errors surface their real first line (not
  a blank "could not be completed") with an auth/rate-limit/timeout/network/model
  category badge.
- **Long-task robustness.** Per-session event cache (switching no longer flashes/
  refetches); turn-list windowing to the last 60 (bounds the DOM on huge runs) with
  "load earlier"; auto-follow respects manual scroll-up + a "Jump to latest" pill.
- **Interaction.** Queue-while-running (type a follow-up mid-run; it sends at the
  next turn boundary — never a fake mid-step injection) + Esc-to-stop; a Ctrl/Cmd+K
  command palette (fuzzy session switch + actions, full keyboard control).
- **Light theme** that follows the OS (`prefers-color-scheme`), a clean remap of the
  existing token system; verified defect-free across the main surfaces.
- **Defects fixed:** `redact()` was scrubbing token *counts* (`*_tokens`) as if they
  were credentials → the meter is now real; workspace-switch was permanently wedged by
  never-cleared completed jobs (`liveJobs.size > 0`) → gated on genuinely-running jobs;
  session↔run coarse-fallback + mojibake goal title.

All front-end + `studio/server.mjs`; no DO_NOT_TOUCH Python touched. Verified per
iteration: tsc + vite build, Studio smokes/contracts, and live preview on a real
captured run. Deferred (tracked in the plan): finalized-turn memoization + true
virtualization, seq-cursor SSE backfill, edit-and-resend, inline diff accept/reject,
session backup/branch/restore, a manual theme toggle.

### Studio — main content-area liveness (S76 · iteration 1)

Fixes the "thought for a long time, not a single word, then a review popped up —
feels like a state machine" report. The backend was genuinely streaming (96 real
model deltas incl. reasoning); the main thread was silently dropping them.

- **Prefer the session's own streamed events.** The thread fell back to coarse
  runtime phase-labels (which drop every token delta lacking a `transcript_kind`)
  whenever the session's `run_id` didn't match the run detail. Now it renders the
  session's own model/tool/file/final events whenever they exist, so the real token
  stream shows instead of "Thinking / Checking the work" placeholders. This also
  fixes the mojibake goal title (it came from that coarse path).
- **Reasoning persists after completion.** Thinking was surgically deleted the
  instant a final answer arrived. It now collapses into a re-openable "Thought for
  Xs" chip (real elapsed; token count only from real telemetry; raw `<think>`
  cleaned; no chip when empty).
- **Process cards persist.** Tool-call and permission cards render inline after a
  turn completes instead of hiding behind a closed "Ran N actions" badge; softer
  plan/verification detail stays foldable; diffs unchanged.
- **Workspace switch no longer wedges.** Completed jobs were never removed from the
  live-job map, so `liveJobs.size > 0` blocked every workspace switch after the
  first run; the guard now checks for genuinely running jobs.

Verified: tsc + vite build, server.mjs syntax, 4 thread smokes, and a real captured
run (the reported snake-game session) now rendering its streamed reasoning + correct
Chinese with no console errors. Front-end only + one server guard; no DO_NOT_TOUCH
file touched. Long-task virtualization, SSE reconnection, and session backup/restore
follow in later iterations of the plan.

### Beta-safety prerequisite + verification-gate honesty

Research-driven (Codex / Claude Code / OpenCode / Aider) Beta-safety prerequisite
plus verification-gate honesty. All in-bounds — no changes to the frozen core
command layer (execute/run/gate/acceptance).

### Added
- **Beta-safe access profile** — a named capability profile (`beta_safe`) that
  hard-disables shell execution and network egress at the policy layer, mirroring
  Codex `read-only` / Claude Code `default`. Pin a shared/external Beta deployment
  by setting `"active_access_profile": "beta_safe"` in `.asteria/policies.json`
  (one line; profile defined in code). Resolved at the single `load_policy_config`
  load point, so every command sees the restricted permissions with no run/execute
  path changes. `asteria doctor` shows the active profile and the effective
  shell/network state so an operator can verify the deployment is locked down.

### Changed (honesty)
- `/run` docs no longer draw review inside the auto flow — verification is an
  explicit step (`review` / `accept`), surfaced in Studio via the
  "done ≠ verified" hint. Mainstream tools verify via opt-in/hooks rather than
  baking it into the core loop.
- Repair bounding: documented that the effective bound is the derived inner-cycle
  cap + no-progress detection (the mainstream shape). The unused cross-run
  `max_repair_attempts_total` ledger is intentionally not wired, not a pending gap.

## [0.2.0a2] — 2026-07-02

Honesty + security convergence after a full-system "docs claim vs code reality"
audit. Principle: never emit an outcome/label/evidence that claims a capability
ran when it did not; close real closure-breakpoints; add mainstream coding-agent
table stakes — without modifying the frozen core command layer (DO_NOT_TOUCH).

### Security (P0)
- ShellGuard: protected-path/secret pre-scan (`cat .env` blocked), `allow_network`
  gate (curl/wget/nc/ssh/git-clone), destructive-command deep scan (find -delete,
  interpreter rmtree, quoted Remove-Item), `.asteria/` added to protected paths
  (policy self-escalation), plus a two-round red-team pass.
- runtime_request packaged-schema enum sync + validated rewrite (poisoning fix).
- Honest scope: a static shell denylist is a speed-bump, not a boundary — an
  external Beta should constrain/close shell or run a sandbox.

### Trust (P1)
- Remove the dead `approve_similar_for_session` option and the fake
  `execution_approval_applied` effect it recorded.
- MCP/Skill `ask` was a no-op (nothing consumed `requires_decision`) → report the
  honest `allow` (contract-gated); docs downgraded.
- Studio: drop the chat keyword short-circuit that returned a canned template;
  disclose built-in template answers; "AI Debug Agent" → "Run Diagnostics"; stop
  fabricating "Done." for content-less finals; fix the plan opening step mislabeled
  as the run result; offline-warning now covers the default route.

### Closure breakpoints (P2)
- MCP/Skill tool observations re-loop into the next round (were dropped at the
  round boundary); glob/diff_workspace/todo_read/todo_write unblocked (stale
  capability-kind map + planner contract); route fallback persisted to
  model_calls.jsonl; bounded chat history so Studio chat is no longer single-turn.

### Desktop table stakes (P3)
- Stop/interrupt a running run (session stop route + tree-kill + Composer Stop);
  session search; run token-usage panel (no fabricated USD cost); Inspector renders
  MCP/Skill invocations + capability decisions and stops truncating the file list;
  live streaming shows real model deltas instead of a placeholder; event-id
  namespace unified + replay de-duplicated.

### Debt / honesty (P4)
- `init` is idempotent (never overwrites user-edited managed files; `--force` now
  actually regenerates); a dead MCP server degrades to "no tools" instead of
  crashing the run; user_progress `session_id` is no longer written null; doc
  over-claims (fork / auto-compaction / `--model-strategy local` / max_total_minutes)
  downgraded to reality.

Verification: unit 902 + integration + ruff + doc-contracts 22 + Studio build/smoke,
all green; no DO_NOT_TOUCH file modified. Items needing the frozen core (real /run
review gate, repair-budget enforcement, schema-drift sync, Studio session-id
plumbing, acceptance scoring) remain flagged DecisionPoints.

## [0.2.0a1] — 2026-06-28

First releasable alpha. Focus: make the core Goal→Plan→Execute→Verify loop
reliable on real providers, and converge the project after over-built scaffolding.

### Reliability — model delegation & loop convergence
- Default task execution and repair to the **strong** model tier; strong/weak
  tiers are a delegation mechanism with an explicit per-task `execution_tier`
  downgrade for basic grunt work. A corrective retry always runs on strong.
- Agent loop converges over multiple rounds (`agent_loop.max_rounds_per_task`
  2 → 5, policy-driven) — Claude-Code-style tool→verify→retry within one session.
- CoderAgent: ungrounded-stop corrective retry that names the unwritten target
  and forbids premature stop/ask/replan.
- Result: on real-provider `small_code_change` goldens, model-compliance
  failures (ungrounded stop / no-write) are eliminated; runs converge in a
  single round or self-heal across rounds.

### Provider hardening
- Retry on empty/whitespace streaming responses (no tool calls) instead of
  silently accepting them.
- ReviewAgent fallback now shares a total time budget (`review_fallback_total_seconds`,
  default 120s) so tier fallback cannot blow the task deadline.

### Packaging (release-blocking fixes)
- Bundle **all** runtime JSON schemas in the wheel. Nine were missing from the
  packaged directory (including `run_config.schema.json`), which crashed
  `asteria goal` from an installed wheel with `Schema not found`.
- New regression guard (`tests/unit/test_schema_packaging.py`) fails if any
  repo-root schema is missing from the packaged directory.
- Wheel install smoke (`scripts/s15_wheel_install_smoke.py`) gains `--rebuild`
  for a clean build, so release sign-off cannot reuse a stale wheel.
- Real-provider wheel sign-off verified end-to-end: fresh venv → install wheel →
  `asteria goal` → produced and behavior-checked artifact.

### Convergence / cleanup
- Removed ~9.9k lines of frozen, default-disabled orchestration/swarm execution
  machinery (15 modules + 23 tests + 12 orphaned gates); kept read-only fanout
  and `asteria route`. See `docs/zh/已删除与已替代登记.md`.
- Documentation converged to a single source; historical report snapshots pruned.
- Cleared ruff lint debt.

[0.2.0a1]: https://github.com/z243802480/mult_agent_code/releases/tag/v0.2.0a1
