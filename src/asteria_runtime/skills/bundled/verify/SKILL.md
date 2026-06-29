---
name: verify
description: Verify the current change by running the project's tests and summarizing pass/fail honestly, with the first failing output. Use before claiming a task is done.
---

# Verify a change

Use this procedure to check whether the current change actually works, using your existing tools.
Loading this skill gives you the procedure; you carry it out with the normal read/test tools.

## Steps

1. Identify the project's test command (e.g. `pytest -q`, `npm test`, `cargo test`). Prefer the
   command configured for this workspace; if unsure, read the project config
   (`pyproject.toml`, `package.json`, etc.) with `read_file`.
2. Run it with the `run_tests` tool (not a raw shell pipeline). Keep the command bounded.
3. If it passes: summarize "verification passed" with the command used and a one-line result.
4. If it fails: read the failing output, identify the first real failure (ignore noise), and
   summarize which test failed and why in one or two sentences. Do not claim success.
5. Never fabricate a pass. If you could not run verification at all, say so explicitly and
   propose the next step (repair, replan, or ask the user).

## Output

A short, honest verdict: pass or fail, the command used, and — on failure — the first failing
test and its cause. Raw output stays in the evidence / Inspector, not the conversational summary.
