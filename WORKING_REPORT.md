## 2026-05-23 22:14:05 +08:00 automated heartbeat check

### Modified files
- `WORKING_REPORT.md`: added this heartbeat check, validation results, and DecisionPoint notes.

### Reasons
- The workspace already has many uncommitted edits and new files, including `src/asteria_runtime/commands/accept_command.py`, `tests/unit/test_accept_command.py`, several control-surface commands, and schemas. To preserve user-authored work and keep this heartbeat reviewable, this round does not stack another code change on top of the dirty tree.
- The current docs call for the normal user journey to converge on `init -> run -> status -> resume -> review -> accept`; the existing `accept` command and control-surface tests are the safest narrow slice to validate first.

### Test/build results
- `python -m pytest tests/unit/test_accept_command.py tests/unit/test_control_surface_commands.py -q`: passed, 32 passed.
- `ruff check src/asteria_runtime/commands/accept_command.py tests/unit/test_accept_command.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- DecisionPoint: because the workspace has many uncommitted changes, this automation should not guess ownership or add more implementation before the current scope is reviewed. Next round should first confirm whether the dirty tree is expected before running larger checks such as `pytest`, `ruff check .`, or `mypy src`.
- Chinese docs may render garbled through direct PowerShell output; Python `utf-8-sig` reads them correctly. Future rounds should read Chinese docs through Python to avoid misinterpreting roadmap content.

### Suggested smallest next task
- Check whether the `accept` command is fully reflected in README and the Chinese command-surface docs. If not, add one small user-journey paragraph and run the related CLI/doc tests.

### Suggested review focus for tomorrow
- Review whether `accept` should default to approving pending promotions, or whether promotion approval should require a more explicit human action.
- Review whether the current dirty tree is all part of the same command-surface / accept-workflow thread, to avoid merging an oversized change set.


## 2026-05-23 22:31:40 +08:00 automated heartbeat check

### Modified files
- `WORKING_REPORT.md`: appended this second heartbeat check and validation record.

### Reasons
- `AGENTS.md` exists and the workspace still has many pre-existing uncommitted changes. To avoid overwriting or interleaving with user-authored work, this round did not change runtime code.
- The roadmap and Claude Code learning plan emphasize command-surface convergence and the normal user journey ending in `review -> accept`. This round verified the existing `accept` CLI surface directly instead of guessing a larger implementation task.

### Test/build results
- `python -m asteria_runtime accept --help`: passed; the CLI exposes `--root`, `--session-id/--run-id`, `--skip-review`, `--no-promote`, and `--json`.
- `python -m pytest tests/unit/test_accept_command.py -q`: passed, 2 passed.
- `ruff check src/asteria_runtime/commands/accept_command.py tests/unit/test_accept_command.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- DecisionPoint remains open: the dirty tree includes many modified files and untracked implementation/schema files. The automation should not add broader code changes until the current change set is reviewed or intentionally accepted as one coherent branch of work.
- Reading Chinese docs by literal filename through PowerShell/Python command text is fragile in this terminal encoding. Future rounds should discover matching files with `Path('docs/zh').glob('*.md')` and filter by substrings from decoded filenames, or use PowerShell `-LiteralPath` only after obtaining paths from `Get-ChildItem`.

### Suggested smallest next task
- If the dirty tree is confirmed intentional, add a small README/Chinese command-surface doc note for `asteria accept`, then validate with `python -m asteria_runtime accept --help` and targeted tests.

### Suggested review focus for tomorrow
- Confirm whether `accept --no-promote` is the right escape hatch for teams that require explicit promotion approval.
- Confirm whether the current README changes from slash commands to plain commands should be mirrored consistently in the Chinese runtime-command and command-surface convergence docs.

## 2026-05-23 22:40:30 +08:00 automated heartbeat check

### Modified files
- None in this heartbeat. The working tree is clean after the previous commit and push.

### Reasons
- The heartbeat instruction says to commit and push if there is too much uncommitted code. The repository is already on `codex/runtime-control-surface-accept`, tracking `origin/codex/runtime-control-surface-accept`, with latest commit `269f147 Add accept workflow and runtime control signals`, so no additional commit was needed.
- Ran a read-only runtime status check to verify the newly pushed branch still exposes a coherent control surface.

### Test/build results
- `python -m asteria_runtime status --root . --json`: passed. It reports the workspace is initialized and currently blocked by an older pending runtime decision (`decision-0001`) in session `run-20260521-0006`.
- `git ls-remote --heads origin codex/runtime-control-surface-accept`: passed and confirms remote branch commit `269f147f1d82d34e28f4022d94503e42cb702100` exists.

### DecisionPoint / unresolved issues
- There is an existing runtime-level pending decision for a previous Qingdao travel-plan run: `asteria decide --decision-id decision-0001`. This appears unrelated to the code branch and should not be auto-resolved by the heartbeat.
- GitHub CLI is not installed locally, so the branch was pushed but the PR still needs to be opened manually from the GitHub link provided earlier.

### Suggested smallest next task
- Open a draft PR for `codex/runtime-control-surface-accept` and review whether `WORKING_REPORT.md` should remain committed or be moved to local-only operational notes.

### Suggested review focus for tomorrow
- Review the pending runtime decision separately from the code branch; it is product evidence that the control surface correctly blocks on scope expansion rather than silently proceeding.

## 2026-05-23 22:56:00 +08:00 automated heartbeat check

### Substantive artifact change this round
- Added a Quick Start workflow sentence to `README.md` documenting the normal `init -> run -> status -> resume -> review -> accept` path and the role of `asteria accept`.

### Modified files
- `README.md`: documented the default user workflow and final acceptance step.
- `WORKING_REPORT.md`: recorded this heartbeat, rationale, validation, and next review focus.

### Reasons
- The current roadmap and Claude Code learning plan call out command-surface convergence and a user-facing workflow rather than exposing internal command stages. After the previous merge added the `accept` command, the README still did not make the full user path explicit.
- This is a small documentation-only product improvement that avoids changing acceptance policy semantics such as whether promotion approval should be automatic by default.

### Test/build results
- `python -m asteria_runtime accept --help`: passed and confirms the documented final command is exposed.
- `ruff check README.md`: passed with the expected warning that no Python files were found under the Markdown path.

### DecisionPoint / unresolved issues
- The default behavior of `asteria accept` still deserves product review: automatic pending-promotion approval is convenient, but some users may expect explicit approval unless they opt in.
- Chinese command docs may still need the same workflow wording, but this heartbeat intentionally kept the change to one documentation file plus the report.

### Suggested smallest next task
- Mirror the same `init -> run -> status -> resume -> review -> accept` workflow wording into the Chinese runtime-command or command-surface convergence document, using Python `utf-8-sig` path discovery to avoid terminal encoding issues.

### Suggested review focus for tomorrow
- Review whether README should describe `asteria decide` explicitly in Quick Start or leave it as part of the blocked-run/resume path.

## 2026-05-23 23:12:00 +08:00 automated heartbeat check

### Substantive artifact change this round
- Mirrored the default `init -> run -> status -> resume -> review -> accept` user workflow into the Chinese runtime-command reference.

### Modified files
- the Chinese runtime-command reference: added section `1.2 default user workflow` describing the normal user path and clarifying that `accept` is distinct from the `acceptance` test suite and promotion internals.
- `WORKING_REPORT.md`: recorded this heartbeat, rationale, validation, and next review focus.

### Reasons
- The Chinese docs are the project source of truth, while the previous heartbeat only updated the English README. This round keeps the command reference aligned with the command-surface convergence plan.
- The change is documentation-only, small, and avoids changing open product policy questions such as whether `accept` should auto-approve pending promotions.

### Test/build results
- `python -m asteria_runtime accept --help`: passed and confirms the documented final command is available.
- Python doc assertions against the Chinese runtime-command reference: passed for the workflow string, section heading, and `accept`/`acceptance` distinction.
- `ruff check README.md`: passed with the expected Markdown/no-Python-files warning.

### DecisionPoint / unresolved issues
- `accept` default promotion semantics still need human product review before changing behavior.
- GitHub CLI remains unavailable locally, so branches can be pushed but PR creation must use the GitHub web link unless `gh` is installed.

### Suggested smallest next task
- Add a small CLI help or status test that asserts `accept` appears in the Start/default workflow group, if such grouping is intended to be stable.

### Suggested review focus for tomorrow
- Review whether the Chinese command reference should rename slash-style section headings like `/init` to plain `init`, or keep slash aliases as compatibility notes.

## 2026-05-23 23:22:00 +08:00 automated heartbeat check

### Substantive artifact change this round
- Added a regression test that locks `accept` into the top-level Start help group after the documented `init -> run -> status -> resume -> review -> accept` workflow.

### Modified files
- `tests/unit/test_cli.py`: asserts `accept` appears in the default Start command surface and before the Maintain section.
- `WORKING_REPORT.md`: recorded this heartbeat, rationale, validation, and next review focus.

### Reasons
- The command-surface convergence docs say ordinary users should see the Start workflow, not internal command lists. The help output already includes `accept`; this test makes that product contract durable.
- This is a narrow non-invasive test change that does not alter runtime behavior or the open product question about `accept` promotion defaults.

### Test/build results
- `python -m pytest tests/unit/test_cli.py -q`: passed, 7 passed.
- `ruff check tests/unit/test_cli.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- `accept` default promotion semantics still need product review before behavior changes.
- The branch has multiple documentation/test commits and still needs PR creation or merge review; GitHub CLI is not installed locally.

### Suggested smallest next task
- Add one focused test for slash alias parsing of `/accept`, if not already covered, so old-style command compatibility stays explicit while docs move toward plain commands.

### Suggested review focus for tomorrow
- Review whether the top-level help text should explicitly show the workflow order in one line, or whether the grouped Start list is sufficient.

## 2026-05-23 23:32:00 +08:00 automated heartbeat check

### Substantive artifact change this round
- Added explicit parser coverage for the `/accept` slash alias, including `--session-id`, `--no-promote`, and `--json`.

### Modified files
- `tests/unit/test_cli.py`: verifies `/accept` remains compatible while documentation moves the default user surface toward plain `accept`.
- `WORKING_REPORT.md`: recorded this heartbeat, rationale, validation, and next review focus.

### Reasons
- The Chinese command docs still contain slash-style command sections, while README/help now emphasize plain command names. Keeping slash alias coverage explicit prevents compatibility drift during command-surface convergence.
- The test is a small, safe addition that does not change runtime behavior or decide the open product question about default promotion approval.

### Test/build results
- `python -m pytest tests/unit/test_cli.py -q`: passed, 7 passed.
- `ruff check tests/unit/test_cli.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- The branch still needs review/PR or merge. GitHub CLI is not installed locally, so PR creation remains manual.
- Slash aliases remain documented in headings; a future doc cleanup should decide whether to keep slash headings or convert them to plain command names with slash aliases noted as compatibility.

### Suggested smallest next task
- Add a short note in the Chinese runtime-command naming/compatibility section that slash-prefixed commands are aliases, while plain `asteria <command>` is the preferred public form.

### Suggested review focus for tomorrow
- Review whether tests should assert every Start command has both plain and slash parsing, or whether targeted coverage for changed commands is enough.

## 2026-05-23 23:48:00 +08:00 automated heartbeat check

### 30-minute iteration goal
- Complete the plain-command vs slash-alias compatibility loop for the Start workflow: document the preferred public form and lock parsing coverage for all Start commands.

### Substantive artifact change this round
- Added a Chinese command-reference note that new user-facing docs should prefer plain `asteria <command>` examples, while slash-prefixed forms remain compatibility aliases.
- Added a CLI regression test that checks every Start workflow command (`init`, `run`, `status`, `resume`, `review`, `accept`) parses in both plain and slash forms.

### Modified files
- the Chinese runtime-command reference: documents plain-command preference and slash alias compatibility.
- `tests/unit/test_cli.py`: adds Start workflow plain/slash parser coverage.
- `WORKING_REPORT.md`: records this heartbeat, rationale, validation, unresolved issues, and next target.

### Reasons
- The roadmap freezes the ordinary user path as `init -> run -> status -> resume -> review -> accept`, while older docs still use slash headings. This iteration makes the migration rule explicit and protects compatibility in tests.
- This is a medium-granularity documentation + test alignment, not a behavior change, so it avoids deciding open product semantics such as automatic promotion approval.

### Test/build results
- `python -m pytest tests/unit/test_cli.py -q`: passed, 8 passed.
- `ruff check tests/unit/test_cli.py`: passed, All checks passed.
- Python assertions against the Chinese runtime-command reference: passed for plain-command preference, `asteria accept`, `/accept`, and compatibility alias wording.

### DecisionPoint / unresolved issues
- Slash-style section headings remain throughout the long command reference. Renaming all headings would be a broader doc migration and should be reviewed separately.
- GitHub CLI is still unavailable, so PR creation remains manual even though the branch can be pushed.

### Suggested next 30-minute iteration target
- Add an `accept` subsection to the Chinese runtime-command reference that defines purpose, inputs, state changes, outputs, blockers, and safety notes, aligned with the implemented `AcceptCommand`.

### Suggested review focus for tomorrow
- Review whether plain-command preference should be applied to all README/docs examples immediately or only when touching nearby sections.

## 2026-05-24 00:06:00 +08:00 automated heartbeat check

### 30-minute iteration goal
- Complete the Chinese command-reference documentation for the implemented `accept` workflow so the source-of-truth docs cover purpose, invocation, flow, state changes, artifacts, blockers, and safety boundaries.

### Substantive artifact change this round
- Added a full `accept` command section to the Chinese runtime-command reference, aligned with the implemented `AcceptCommand` behavior.
- Verified the docs against the actual CLI help and targeted unit tests for accept/CLI parsing.

### Modified files
- the Chinese runtime-command reference: adds the `accept` command reference section.
- `WORKING_REPORT.md`: records this heartbeat, validation, open decisions, and next target.

### Reasons
- The project guidance says Chinese docs are the source of truth, and previous iterations established `accept` as part of the default user workflow. The command reference needed the actual behavior documented, not only the workflow list.
- The section avoids changing the open product policy about automatic promotion approval; it documents current behavior and explicitly marks default promotion semantics as a DecisionPoint if changed later.

### Test/build results
- Python assertions against the Chinese runtime-command reference: passed for `accept` section, `acceptance` distinction, `--no-promote`, state transitions, event names, and DecisionPoint note.
- `python -m asteria_runtime accept --help`: passed.
- `python -m pytest tests/unit/test_accept_command.py tests/unit/test_cli.py -q`: passed, 10 passed.
- `ruff check tests/unit/test_cli.py src/asteria_runtime/commands/accept_command.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- If the product wants stricter human approval, `accept` default promotion behavior should be changed only after a user-visible DecisionPoint/RFC.
- The Chinese command reference now has two `3.8` headings (`accept` and `debug`); renumbering the long document is a broader doc-maintenance task and should be done separately to avoid noisy diffs.

### Suggested next 30-minute iteration target
- Renumber the affected command-reference headings around `accept/debug/handoff` in a small controlled doc-only pass, with assertions that key anchors still exist.

### Suggested review focus for tomorrow
- Review whether the documented `accept --skip-review` positioning as a controlled/test path is acceptable, or whether it should be hidden from ordinary user docs.

## 2026-05-24 02:57:00 +08:00 automated heartbeat check

### Iteration goal
- Complete a documentation-contract loop for the command-surface migration: README, Chinese runtime-command docs, and tests now agree that plain commands are preferred while slash-prefixed commands remain compatibility aliases.

### Substantive artifact change this round
- Added a README note for plain command names and slash alias compatibility.
- Added documentation contract tests that verify the README source-of-truth link exists, README documents alias compatibility, and the Chinese runtime-command reference keeps the accept workflow and alias-policy fragments.

### Modified files
- `README.md`: documents plain-command preference and slash alias compatibility for older automation.
- `tests/unit/test_documentation_contracts.py`: new documentation contract tests for README and Chinese runtime-command docs.
- `WORKING_REPORT.md`: records this iteration, validation, open issues, and next target.

### Reasons
- Previous iterations updated docs and CLI tests, but there was no dedicated test guarding the README/source-of-truth and Chinese-doc workflow contract. This closes the loop and prevents future mojibake/link regressions or accidental removal of the alias policy.
- The change is user-visible documentation plus durable tests, without changing runtime behavior or open product decisions around automatic promotion approval.

### Test/build results
- `python -m pytest tests/unit/test_documentation_contracts.py tests/unit/test_cli.py tests/unit/test_accept_command.py -q`: passed, 12 passed.
- `ruff check tests/unit/test_documentation_contracts.py tests/unit/test_cli.py src/asteria_runtime/commands/accept_command.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- GitHub CLI is still unavailable locally, so PR creation remains manual even though this branch is pushed.
- The Chinese command reference still has numbering drift after inserting `accept`; renumbering should be done as a separate doc-only pass.

### Suggested next medium-granularity target
- Renumber the affected Chinese command-reference sections around `accept`, `debug`, and `handoff`, and add a doc assertion that these key sections appear in the expected order.

### Suggested review focus for tomorrow
- Review whether the README compatibility note is enough for migration, or whether the CLI help should also explicitly say slash-prefixed forms are compatibility aliases.

## 2026-05-24 03:16:00 +08:00 automated heartbeat check

### Iteration goal
- Finish the command-reference cleanup introduced by adding `accept`: remove duplicate section numbering and guard the user workflow section order with tests.

### Substantive artifact change this round
- Renumbered the affected Chinese runtime-command sections from `accept/debug/handoff` so `accept` owns `3.8`, `debug` becomes `3.9`, and `handoff` becomes `3.10`.
- Added a documentation contract test that asserts `resume -> review -> accept -> debug -> handoff` appears in order and that there is only one `3.8` command heading.

### Modified files
- `docs/zh/????.md`: fixes command-reference numbering around `accept`, `debug`, and `handoff`.
- `tests/unit/test_documentation_contracts.py`: adds section-order and duplicate-heading regression coverage.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The previous `accept` insertion left two `3.8` headings, which weakens the source-of-truth command reference. This iteration makes the documentation internally consistent and protects the ordering with a targeted test.
- The change is a cohesive doc/test maintenance pass and does not alter runtime behavior.

### Test/build results
- `python -m pytest tests/unit/test_documentation_contracts.py tests/unit/test_cli.py tests/unit/test_accept_command.py -q`: passed, 13 passed.
- `ruff check tests/unit/test_documentation_contracts.py tests/unit/test_cli.py src/asteria_runtime/commands/accept_command.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- The command reference still contains many slash-style headings by design; broader conversion to plain headings should be reviewed separately.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add a small user-facing CLI help line or epilog explaining that slash-prefixed commands are compatibility aliases, and extend CLI tests to cover that text.

### Suggested review focus for tomorrow
- Review whether `accept` should remain before `debug` in the reference because it is a user-workflow command, while `debug` is an advanced repair command.

## 2026-05-24 03:31:00 +08:00 automated heartbeat check

### Iteration goal
- Make the CLI help surface match the documented plain-command workflow by explaining slash-prefixed aliases directly in user-facing help.

### Substantive artifact change this round
- Added a shared slash-alias compatibility help message to the top-level CLI help and the default workflow commands (`init`, `run`, `status`, `resume`, `review`, `accept`).
- Removed slash-prefixed wording from `run` and `resume` option help so new help text prefers plain commands while keeping slash aliases functional.
- Added regression coverage for the top-level compatibility section and all default workflow command help pages.

### Modified files
- `src/asteria_runtime/cli.py`: adds the compatibility help constant, wires it into relevant help output, and normalizes `run`/`resume` option wording.
- `tests/unit/test_cli.py`: verifies the plain-command/slash-alias help contract and guards against reintroducing slash-first option wording.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The Chinese command reference and README already say new docs/scripts should prefer plain command names, while slash-prefixed forms are compatibility aliases. CLI help was the remaining user-facing surface that did not make this explicit.
- A single shared message keeps the policy consistent across the top-level help and the default workflow commands.

### Test/build results
- `python -m pytest tests/unit/test_cli.py tests/unit/test_documentation_contracts.py -q`: passed, 12 passed.
- `ruff check src/asteria_runtime/cli.py tests/unit/test_cli.py tests/unit/test_documentation_contracts.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- Slash aliases remain available and are still shown by argparse in some compatibility contexts; a broader deprecation/migration plan would need an explicit product decision.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add a small documentation/CLI contract around `acceptance` versus `accept` so ordinary users do not confuse finalizing a reviewed run with running validation suites.

### Suggested review focus for tomorrow
- Review whether the compatibility help wording is clear enough for both new users and older automation owners.

## 2026-05-24 03:46:00 +08:00 automated heartbeat check

### Iteration goal
- Clarify the `accept` versus `acceptance` split across CLI help, README, and tests so ordinary users can complete a run without confusing completion with validation suites.

### Substantive artifact change this round
- Added a shared CLI help note explaining that `accept` finalizes one reviewed run while `acceptance` runs validation suites for maintainers and CI.
- Exposed that note in top-level help plus `accept` and `acceptance` command help.
- Updated README quick-start wording to keep `acceptance` out of the ordinary user completion path.
- Added CLI and documentation contract tests for the distinction.

### Modified files
- `src/asteria_runtime/cli.py`: adds the `accept`/`acceptance` distinction to user-facing help.
- `README.md`: documents the same distinction in the quick-start workflow.
- `tests/unit/test_cli.py`: covers top-level and command-specific help text.
- `tests/unit/test_documentation_contracts.py`: guards the README quick-start contract.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The Chinese source-of-truth already says `accept` is the ordinary workflow closer and is not `acceptance`; the CLI and README needed the same explicit user-facing distinction.
- This is a cohesive command-experience improvement and does not change runtime behavior.

### Test/build results
- `python -m pytest tests/unit/test_cli.py tests/unit/test_documentation_contracts.py -q`: passed, 13 passed.
- `ruff check src/asteria_runtime/cli.py tests/unit/test_cli.py tests/unit/test_documentation_contracts.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- No product policy change was made: `acceptance` remains available as a maintainer/CI command.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add a compact CLI smoke/help contract for `gate`, `gray`, and `acceptance` so maintainer-facing commands remain clearly separate from the default user workflow.

### Suggested review focus for tomorrow
- Review whether the `accept`/`acceptance` wording is sufficiently clear for non-maintainer users.

## 2026-05-24 04:01:00 +08:00 automated heartbeat check

### Iteration goal
- Keep maintainer-facing validation commands (`gate`, `gray`, `acceptance`, `acceptance-gate`) clearly outside the ordinary user completion workflow in CLI help and quick-start docs.

### Substantive artifact change this round
- Added a shared maintainer/CI help note to top-level CLI help and the relevant maintainer command help pages.
- Extended README quick-start to separate validation/release commands from the `init -> run -> status -> resume -> review -> accept` completion path.
- Added CLI and documentation contract tests that guard this command-surface separation.

### Modified files
- `src/asteria_runtime/cli.py`: adds the maintainer command help note and wires it into `gate`, `gray`, `acceptance`, and `acceptance-gate`.
- `README.md`: documents that maintainer validation commands are not ordinary completion steps.
- `tests/unit/test_cli.py`: verifies maintainer command help includes the separation note and `accept` does not.
- `tests/unit/test_documentation_contracts.py`: guards README quick-start wording for maintainer validation commands.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- Recent iterations clarified the default workflow and `accept`/`acceptance`; this closes the adjacent UX gap for `gate` and `gray`, which are important but should not become ordinary user mental-model requirements.
- The change is user-visible help/documentation behavior with regression tests, without altering runtime execution.

### Test/build results
- `python -m pytest tests/unit/test_cli.py tests/unit/test_documentation_contracts.py -q`: passed, 14 passed.
- `ruff check src/asteria_runtime/cli.py tests/unit/test_cli.py tests/unit/test_documentation_contracts.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- No command deprecation was introduced; this only clarifies command audience and usage order.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add command help/documentation checks for machine-readable JSON fields on `status`, `doctor`, and `gate-status`, so future UI/automation can rely on stable control-surface contracts.

### Suggested review focus for tomorrow
- Review whether maintainer/CI language should also appear in the Chinese command reference around the `gate` and `gray` sections.

## 2026-05-24 04:16:00 +08:00 automated heartbeat check

### Iteration goal
- Make machine-readable control-surface JSON from `status`, `doctor`, and `gate-status` self-describing so UI/automation can rely on a stable additive field contract.

### Substantive artifact change this round
- Added a shared `control_surface` contract helper that records command name, audience, additive stability policy, and stable field names.
- Added the contract to `status`, `doctor`, and `gate-status` JSON payloads without changing existing top-level fields.
- Added regression tests that verify each contract is present, identifies the correct command/audience, and only lists fields actually present in the payload.

### Modified files
- `src/asteria_runtime/commands/control_surface_contract.py`: new shared helper for control-surface JSON metadata.
- `src/asteria_runtime/commands/status_command.py`: exposes the user-workflow control-surface contract.
- `src/asteria_runtime/commands/doctor_command.py`: exposes the maintainer preflight control-surface contract.
- `src/asteria_runtime/commands/gate_status_command.py`: exposes the maintainer release-readiness control-surface contract.
- `tests/unit/test_control_surface_commands.py`: adds contract assertions for `status`, `doctor`, and `gate-status`.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The docs say `status --json`, `doctor --json`, and `gate-status --json` are reusable control-surface outputs for future TUI/GUI/automation. A small self-describing contract makes that promise explicit and testable.
- The change is additive and keeps existing JSON fields intact.

### Test/build results
- `python -m pytest tests/unit/test_control_surface_commands.py tests/unit/test_cli.py -q`: passed, 41 passed.
- `ruff check src/asteria_runtime/commands/control_surface_contract.py src/asteria_runtime/commands/status_command.py src/asteria_runtime/commands/doctor_command.py src/asteria_runtime/commands/gate_status_command.py tests/unit/test_control_surface_commands.py tests/unit/test_cli.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- No JSON field deprecation or schema version bump was introduced; formal cross-version compatibility policy can be documented separately if needed.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Document the new `control_surface` contract in `docs/zh/????.md` and add documentation contract tests for its stable field/audience semantics.

### Suggested review focus for tomorrow
- Review whether `control_surface.stability=additive` is the right compatibility promise before relying on it from UI/automation.

## 2026-05-24 04:35:00 +08:00 automated heartbeat check

### Iteration goal
- Close the documentation loop for the new `control_surface` JSON contract added to `status`, `doctor`, and `gate-status`.

### Substantive artifact change this round
- Documented `control_surface`, `stable_fields`, `stability=additive`, and command audiences in the Chinese runtime command source of truth.
- Added a documentation contract test that guards the control-surface semantics and the required audiences for `status`, `doctor`, and `gate-status`.

### Modified files
- `docs/zh/????.md`: explains the control-surface metadata contract and its additive compatibility promise.
- `tests/unit/test_documentation_contracts.py`: adds regression coverage for the documented contract.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The previous iteration added the JSON metadata in code; this iteration makes the source-of-truth docs match the runtime behavior and protects it with tests.
- This keeps future UI/automation consumers aligned on which fields are stable and when a DecisionPoint is required.

### Test/build results
- `python -m pytest tests/unit/test_documentation_contracts.py tests/unit/test_control_surface_commands.py -q`: passed, 34 passed.
- `ruff check tests/unit/test_documentation_contracts.py tests/unit/test_control_surface_commands.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- The additive compatibility promise is now documented; any future removal/rename/semantic change must be handled as a DecisionPoint.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add a small machine-readable example fixture for `status --json` that includes `control_surface`, then use it in docs/tests as an executable contract sample.

### Suggested review focus for tomorrow
- Review whether `stable_fields` should eventually move into JSON Schema files for stronger validation beyond unit tests.

## 2026-05-24 04:50:00 +08:00 automated heartbeat check

### Iteration goal
- Add an executable `status --json` control-surface example fixture and bind it to the documented contract.

### Substantive artifact change this round
- Added `docs/en/examples/status_control_surface.json` as a minimal machine-readable example containing the new `control_surface` metadata.
- Updated the Chinese runtime command source of truth to point to the example and require `stable_fields` to match top-level fields.
- Added a documentation contract test that loads the JSON example and validates command, audience, additive stability, stable fields, and next-action semantics.

### Modified files
- `docs/en/examples/status_control_surface.json`: new executable JSON example for `status --json` consumers.
- `docs/zh/????.md`: links the example to the control-surface contract and documents the consistency requirement.
- `tests/unit/test_documentation_contracts.py`: validates the example as part of the documentation contract suite.
- `WORKING_REPORT.md`: records this iteration, validation, unresolved issues, and next target.

### Reasons
- The previous two iterations added and documented the control-surface contract; this adds a concrete sample that UI/automation authors can reuse and tests can enforce.
- The change is documentation/test focused but still produces a durable machine-readable artifact.

### Test/build results
- `python -m pytest tests/unit/test_documentation_contracts.py tests/unit/test_control_surface_commands.py -q`: passed, 35 passed.
- `ruff check tests/unit/test_documentation_contracts.py tests/unit/test_control_surface_commands.py`: passed, All checks passed.

### DecisionPoint / unresolved issues
- Only `status --json` has an example fixture for now; `doctor` and `gate-status` examples can be added later if UI/automation consumers need them.
- GitHub CLI is still unavailable locally, so PR creation remains manual.

### Suggested next medium-granularity target
- Add similar example fixtures for `doctor --json` and `gate-status --json`, or move the shared `control_surface` metadata into JSON Schema validation if stronger enforcement is preferred.

### Suggested review focus for tomorrow
- Review whether the example location under `docs/en/examples/` is the right long-term home for machine-readable contract samples.
