---
name: retrospect
description: Before declaring a task done, review your own work against the goal and the evidence — confirm each requirement is met and verified, and honestly flag anything that is not. Use right before finishing.
---

# Review before declaring done

Use this procedure to confirm a task is actually complete against real evidence, instead of
declaring victory on a hunch. Loading this skill gives you the procedure; you carry it out with your
normal read/test tools.

## Steps

1. Restate the goal and its definition of done — the concrete conditions the task had to satisfy.
2. Walk each requirement and point to the evidence that it is met: the artifact exists (`read_file`
   or list it), the behavior works (a `run_tests` / `run_command` that passed with its output). A
   requirement with no evidence is not done.
3. If a requirement has not actually been verified, verify it now — run the test or command rather
   than assuming. Do not treat "I wrote the code" as "the code works".
4. Check your todo list (if you kept one) is fully accounted for — every step done, or explicitly
   dropped with a reason.
5. Be honest about gaps. If something is unverified, partial, or out of scope, say so plainly rather
   than implying the whole task succeeded. Honest "done except X" beats a false "done".
6. Write a short plain-language summary of what changed and how you know it works — the account a
   reviewer would need, in the user's language.

## Output

A short honest close-out: each requirement mapped to the evidence that confirms it, any remaining
gap stated plainly, and a one-paragraph summary of what changed. Raw traces stay in the evidence.
