---
name: debug
description: Find the true root cause of a failure by testing hypotheses against evidence before changing code. Use when a test fails, an error is thrown, or behavior is wrong and the cause is not obvious.
---

# Debug to the root cause

Use this procedure to fix the real cause of a failure instead of guessing at symptoms. Loading this
skill gives you the procedure; you carry it out with your normal read/test/run tools.

## Steps

1. Reproduce first. Run the failing test or command with `run_tests` / `run_command` and capture the
   actual error — the exact message, the failing assertion, the stack frame. Do not theorize before
   you have reproduced.
2. Read the failing site. `read_file` the code named in the trace and the input it received. State
   what the code assumed vs. what actually happened.
3. Form one concrete hypothesis about the cause ("X is None because Y never set it"), narrow enough
   to be wrong. If several are plausible, rank them.
4. Test the hypothesis cheaply: read the relevant path, or add a temporary probe (a log/assert) and
   re-run. Confirm the mechanism before touching the fix — do not fix a guess.
5. Once confirmed, make the smallest change that removes the cause (not just the symptom), remove any
   temporary probe, and re-run the reproduction to prove it is green.
6. If you cannot confirm a cause, say so honestly and report the narrowed-down suspects and the next
   diagnostic step rather than shipping a speculative fix.

## Output

A short honest account: the reproduced failure, the confirmed root cause (with the evidence that
confirmed it), the minimal fix, and the passing re-run. Raw traces stay in the evidence.
