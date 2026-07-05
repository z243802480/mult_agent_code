---
name: minimal-change
description: Make the smallest correct edit that satisfies the goal — match surrounding style, touch only what the task needs, and cover the behavior change with a test. Use when editing existing code.
---

# Make a minimal, correct change

Use this procedure to change existing code without scope creep or collateral damage. Loading this
skill gives you the procedure; you carry it out with your normal edit/test tools.

## Steps

1. Know the target first. Make sure you have the `path:line` where the change belongs and what
   depends on it (investigate first if not). Edit from evidence, not assumption.
2. Prefer a precise edit. Use `edit_file` / `apply_patch` to change only the lines the task needs.
   Never rewrite a whole file to make a small change.
3. Match the surrounding code: its naming, error handling, comment density, and idioms. New code
   should read like it was already there. Do not reformat unrelated lines.
4. Stay in scope. Do not refactor, rename, or "improve" code the task did not ask about, and do not
   touch files marked do-not-touch. If you spot a real unrelated problem, note it separately instead
   of folding it in.
5. Cover the behavior change with a test — add or adjust the test that would have caught the old
   behavior — then run it with `run_tests` to prove the change works and nothing nearby broke.
6. Keep the diff reviewable: if the change is growing large, stop and reconsider whether a smaller
   edit achieves the goal.

## Output

A small, in-style diff that does exactly what the task needs, plus the passing test run that proves
it. Note any out-of-scope issues you deliberately left alone.
