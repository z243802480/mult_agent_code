# Independent repository evaluation protocol

Freeze these before the first goal call: upstream repository/commit and archive hash;
public behavior contract and allowed changes; original file hashes; independent oracle hash;
runtime production hashes; provider/budget/time limit and stop conditions. Keep upstream
license and original tests. Never change a frozen oracle to make the current run pass.

Use separate locations for the target workspace, runtime package, and controller/oracles.
The runtime copy contains only the runtime package/resources, not this repository's tests,
benchmark answers, or controller scripts. Do not put repaired versions or reference solutions
beside the target. The target contains its upstream source, original tests and public task
contract; it contains no runtime copy, hidden checks or control scripts.

State the experimental boundary in the goal and target guidance: work only in the target;
do not scan parents or other experiments; do not read/introspect runtime or installed-package
implementations, reference solutions, hidden checks or controller evidence. Normal invocation
of the declared interpreter/pytest is allowed. This is a controlled local experiment with
behavioral auditing, not an OS sandbox or a guarantee of inaccessible files.

The model receives the complete public acceptance behavior. Fix a field name only when that
name is part of the public API/contract. Otherwise permit semantically equivalent outputs.
Independent checks use that public behavior, not resemblance to the evaluator's solution.
No implementation hints or independent failing cases are injected during the run.

Before Review/Accept, independently run original tests and the frozen oracle; compare every
original file and new file against the allowed scope; inspect source binding and tool inputs
for reference exposure. Any exposure disqualifies independent autonomy even if tests pass.
Also record template fallbacks, unsuccessful exploration, repeated verification, real routes,
usage, pause/cancel and controller intervention separately. Human non-intervention is not
evidence of no answer exposure.

Run the ordinary goal entry with a finite external deadline and the existing global budget.
Use normal pause/cancel for a declared stop condition. A stopped, failed or keyless task is
not a pass. The controller may finish external artifact inspection after a pause, but that
does not change the run into an autonomous completion. One registered run per experiment;
any later run needs a new record and an explicit account of changes between runs.

For a registered pause/resume experiment, state the trigger before the goal call. After
the normal pause has taken effect and its process exited, freeze a checkpoint of goal,
tasks, existing evidence/cost and edited artifacts. Resume that same session in a fresh
process without reissuing the goal or adding solution hints; record both process IDs,
shared deadline/budget and continuity checks. The paused checkpoint is not a completed
result. Qualify the whole experiment only after resume and final independent verification;
do not treat the resumed leg as a fresh zero-cost goal or hide the control interruption.
