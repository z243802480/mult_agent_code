# Changelog

All notable changes to asteria-runtime. This project targets a first releasable
version (v0.2-alpha); entries are distilled from git history, not narrated.

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
