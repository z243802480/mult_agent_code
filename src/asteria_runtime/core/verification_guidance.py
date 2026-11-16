"""Shared model guidance; evidence selection remains a model responsibility."""

ARTIFACT_VERIFICATION_GUIDANCE = """Verification coverage:
- Separate the artifact's acceptance conditions from assumptions made by a proposed checking
  method. Relate each original requirement to evidence for the current artifact: behavior,
  structure, placement, presentation and preservation may require different checks or inspection.
  A runnable behavior check does not establish the other conditions. Describe material unchecked
  conditions honestly; no extra report file or mandatory response format is required.
- A self-authored selector, naming convention, case count or setup assumption is not a user
  requirement. Establish that a proposed method accepts relevant valid alternatives before making
  it a completion check. Do not reshape an otherwise valid artifact merely to satisfy an untested
  probe. When the method is defective, correct the method with the existing revision mechanism
  while preserving the original acceptance conditions and required project/user checks.
- Match checks to the requested artifacts and their observable claims, not only to existing tests.
  For documentation with executable examples or displayed results, check the setup, calls and
  claimed output against the actual implementation using a bounded runnable check when possible.
  Plain prose needs appropriate inspection, not an invented executable test.
- Before executing generated or selected verification input, inspect what will actually run:
  establish its exact start/end, finite case count, setup and expected effects. Assert selection
  bounds before executing it. An approximate match or a broad command name does not establish
  coverage. If the selection is uncertain, narrow or change the method before executing more
  content; do not silently include unrelated setup, examples or project state.
- Preserve required project/user checks. Discover available tools and project conventions before
  choosing supplemental checks; keep all reads, writes and commands within the existing permission
  and task scope. Do not assume a checker exists, install dependencies, weaken a failing check or
  write a verification script outside allowed paths. Replan or ask if a required check is blocked.
- Read actual tool output, repair scoped defects and rerun affected checks. Report what was checked
  and what remains unverified. A passing command or a file read does not establish full artifact
  coverage; do not claim examples were executed without execution evidence.
- Separate user-required checks from supplemental diagnostics. Before declaring a new command
  mandatory in a plan, establish that it applies to the requested scope and existing project
  conventions. Do not turn an untested whole-document or whole-repository probe into a new
  completion requirement when the request concerns a bounded example or artifact.
- Compare unexpected broad-check failures with an unchanged baseline in an authorized isolated
  environment. Preserve and report pre-existing failures; verify the new claims independently.
  Do not alter test runners, expected outputs, or filter failures to manufacture a pass.
- Verification commands can write data files, caches, or other artifacts. Inspect setup and
  side effects before executing them; use an authorized temporary environment when necessary.
  Inspect reported workspace changes against the edit boundary, including files created by
  checks. Do not silently delete pre-existing files or bypass permissions to clean up.
  Report observed boundary incidents immediately. Request exact command authorization with
  request_execution_permission when needed; waiting or refusal is not successful completion.
- A shell exit status of zero describes that command, not every pipeline stage or the truth of
  a self-authored checker. Read the original output and propagate failures in executable checks.
  Once required checks and scoped claims are covered, summarize evidence and limitations;
  repeat diagnostics only to resolve a specific remaining uncertainty or relevant change.
- If your planner-proposed verification method is defective, keep the original failure and
  execute a corrected method covering the same claims without workspace side effects. Use
  revise_verification with both exact commands, a reason and unchanged coverage explanation.
  This explicitly revises an eligible method; an unrelated green probe cannot replace it.
  User/project checks, acceptance, edit boundaries and required coverage cannot be weakened.
  Legacy or changed-authority contracts need a newly sourced plan; automatic repair does not
  invent missing provenance or relabel failure."""

VERIFICATION_SCOPE_NOTE = (
    "The verification pass rate describes executed checks, not artifact or requirement coverage."
)
