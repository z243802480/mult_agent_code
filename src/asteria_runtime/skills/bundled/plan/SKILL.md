---
name: plan
description: Break a multi-step task into an ordered, externalized plan before diving in, so you work systematically and can track progress. Use at the start of a non-trivial, multi-file, or unfamiliar task.
---

# Plan before executing

Use this procedure to turn a fuzzy goal into an ordered set of concrete steps you can track and
verify, so you work systematically instead of reacting step to step. Loading this skill gives you
the procedure; you carry it out with your normal tools (especially `todo_write`).

## Steps

1. Restate the goal in one sentence and write down its definition of done — the concrete, checkable
   conditions that mean the task is finished (files that must exist, tests that must pass).
2. Decompose into an ordered list of steps. Each step should be a concrete outcome you can verify
   (e.g. "write `foo.py` with `bar()`", "run the tests and see them pass"), narrow enough to know
   when it is done. Investigate first if you do not yet know where the change belongs.
3. Externalize the plan with `todo_write` — one entry per step. This is your working memory; it is
   not enforced, but it keeps you from losing track on a long task and lets progress be seen.
4. Flag risks and unknowns up front — anything that could invalidate the plan (a missing dependency,
   an unclear requirement). Resolve or note them before committing to the order.
5. Keep the plan alive. As you execute, mark steps done and revise the list when you learn something
   that changes the approach. A plan you never update is worse than no plan.

## Output

An ordered todo list capturing the steps and their done-conditions, the first step to act on, and
any risk you resolved or flagged. Simple one-step tasks do not need this — skip it and just act.
