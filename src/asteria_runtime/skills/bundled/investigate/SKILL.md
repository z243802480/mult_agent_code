---
name: investigate
description: Locate and understand the code relevant to a task BEFORE editing it — search first, read only the target, then state what you found. Use at the start of any change to unfamiliar code.
---

# Investigate before changing

Use this procedure to scope a task by finding the exact code that matters, so you edit from
evidence instead of guessing. Loading this skill gives you the procedure; you carry it out with
your normal search/read tools.

## Steps

1. Restate the task in one sentence and list the concrete things you need to find (the function,
   the caller, the config, the test that covers it).
2. Search before reading. Use `list_files` to see structure and narrow by name; grep-style search
   for the symbols/strings from step 1. Do NOT open whole files blindly.
3. `read_file` only the located regions (the target definition, its callers, its tests). Read the
   smallest span that answers "where does this behavior live and what depends on it?".
4. Write down findings as `path:line` references: where the behavior is, what calls it, what tests
   guard it, and any invariant or edge case you must not break.
5. If you cannot find the relevant code, say so explicitly and state your best next search — do not
   invent a location or start editing on a guess.

## Output

A short evidence-grounded map: the 1–5 `path:line` anchors that matter for this task, the
dependency/invariant you must preserve, and a one-line plan for the change. Raw file dumps stay in
the evidence, not the summary.
