"""Shared model guidance; evidence selection remains a model responsibility."""

ARTIFACT_VERIFICATION_GUIDANCE = """Verification coverage:
- Match checks to the requested artifacts and their observable claims, not only to existing tests.
  For documentation with executable examples or displayed results, check the setup, calls and
  claimed output against the actual implementation using a bounded runnable check when possible.
  Plain prose needs appropriate inspection, not an invented executable test.
- Preserve required project/user checks. Discover available tools and project conventions before
  choosing supplemental checks; keep all reads, writes and commands within the existing permission
  and task scope. Do not assume a checker exists, install dependencies, weaken a failing check or
  write a verification script outside allowed paths. Replan or ask if a required check is blocked.
- Read actual tool output, repair scoped defects and rerun affected checks. Report what was checked
  and what remains unverified. A passing command or a file read does not establish full artifact
  coverage; do not claim examples were executed without execution evidence."""

VERIFICATION_SCOPE_NOTE = (
    "The verification pass rate describes executed checks, not artifact or requirement coverage."
)
