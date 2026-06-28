# Changelog

All notable changes to asteria-runtime. This project targets a first releasable
version (v0.2-alpha); entries are distilled from git history, not narrated.

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
