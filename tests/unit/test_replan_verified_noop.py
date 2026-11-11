from pathlib import Path

import pytest

from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.storage.schema_validator import SchemaValidator


def _replan(tmp_path: Path) -> ReplanCommand:
    return ReplanCommand(tmp_path, run_id="run-1")


def _evidence(violations: list[str]) -> dict:
    return {
        "evidence_id": "task-execution-0001",
        "failure_type": None,
        "summary": "task contract not satisfied",
        "contract_check": {"violations": violations},
        "task": {
            "task_id": "task-0001",
            "title": "改 greeter.py",
            "description": "make greet support a greeting parameter",
            "acceptance": ["greet('Alice') == 'Hello, Alice'"],
            "allowed_tools": ["read_file", "write_file", "run_tests"],
            "write_scope": ["greeter.py"],
        },
    }


def _board(tmp_path: Path) -> TaskBoard:
    return TaskBoard(tmp_path / ".asteria" / "agent" / "task_board.json", SchemaValidator(Path.cwd() / "schemas"))


def test_noop_repair_flag_when_whole_complaint_is_untouched_files(tmp_path: Path) -> None:
    # R2-14: the source ran nothing and wrote nothing, so the evidence carries ONLY unproven /
    # untouched-file violations. Nothing proved the artifact wrong — a prior sibling may already
    # have fixed it — so the repair may close by verifying alone instead of being forced into a
    # fresh-diff-or-bust loop that escalates a non-decision to the user.
    cmd = _replan(tmp_path)
    task = cmd._task_from_failure(
        _board(tmp_path),
        _evidence([])["task"],
        _evidence(
            [
                "required verification was not provided",
                "required changed artifact was not produced",
                "expected changed files were not modified: greeter.py",
            ]
        ),
    )
    assert task["verified_noop_allowed"] is True
    # The flag alone would just relabel the loop: without the hint the doer repeats the source's
    # exact behavior (sees a correct file, writes nothing, runs nothing) and gets rejected again
    # for skipping verification.
    assert "Verify-first repair" in task["description"]
    assert "do NOT write" in task["description"]


def test_noop_repair_flag_still_covers_only_unverified(tmp_path: Path) -> None:
    # The original window (never verified) must stay inside the extended one.
    cmd = _replan(tmp_path)
    task = cmd._task_from_failure(
        _board(tmp_path),
        _evidence([])["task"],
        _evidence(["required verification was not provided"]),
    )
    assert task["verified_noop_allowed"] is True


def test_noop_repair_flag_refused_when_verification_actually_failed(tmp_path: Path) -> None:
    # "verification did not pass" says the artifact WAS shown wrong — the repair must fix it, not
    # re-verify it. This is the ring_val_f guardrail, unchanged by the extension.
    cmd = _replan(tmp_path)
    for violations in (
        ["verification did not pass"],
        ["verification did not pass", "expected changed files were not modified: greeter.py"],
        ["verification did not pass", "something brand new"],
    ):
        task = cmd._task_from_failure(_board(tmp_path), _evidence([])["task"], _evidence(violations))
        assert task["verified_noop_allowed"] is False, violations


def test_noop_repair_flag_fails_closed_on_unknown_violations(tmp_path: Path) -> None:
    # Any violation outside the known families disqualifies: the predicate must not silently
    # widen when the contract grows new violation kinds.
    cmd = _replan(tmp_path)
    task = cmd._task_from_failure(
        _board(tmp_path),
        _evidence([])["task"],
        _evidence(["expected changed files were not modified: greeter.py", "some future violation"]),
    )
    assert task["verified_noop_allowed"] is False


@pytest.mark.parametrize('fault', [None, 'no_changes', 'empty_change', 'no_command',
                                 'unknown_violation', 'unidentified_failure'])
def test_prior_artifact_recheck_requires_exact_failed_command_evidence(tmp_path, fault):
    evidence = _evidence(['verification did not pass'])
    evidence['contract_check']['changed_files'] = [] if fault == 'no_changes' else ['greeter.py']
    if fault == 'empty_change':
        evidence['contract_check']['changed_files'] = ['']
    evidence['task_execution_evidence'] = {'verification_results': [{'ok': False,
        'data': {} if fault == 'no_command'
        else {'requested_command': 'python verify_greeter.py', 'command': 'expanded execution'}}]}
    if fault == 'unknown_violation':
        evidence['contract_check']['violations'].append('unknown violation')
    if fault == 'unidentified_failure':
        evidence['task_execution_evidence']['verification_results'].append({'ok': False, 'data': {}})
    source = evidence['task']
    source['validation_commands'] = ['python acceptance.py']
    source['verification_policy'] = {'command_source': 'planner_task'}
    task = _replan(tmp_path)._task_from_failure(_board(tmp_path), source, evidence)
    assert task['verified_noop_allowed'] == (fault is None)
    if fault is None:
        assert task['validation_commands'] == ['python acceptance.py', 'python verify_greeter.py']
        assert task['verification_policy']['command_source'] == 'planner_task'
        assert 'expanded execution' not in task['validation_commands']


def test_recheck_does_not_promote_legacy_validation_prose_to_an_executable_check(tmp_path):
    evidence = _evidence(['verification did not pass'])
    evidence['contract_check']['changed_files'] = ['greeter.py']
    evidence['task_execution_evidence'] = {'verification_results': [
        {'ok': False, 'data': {'command': 'python verify_greeter.py'}}]}
    evidence['task']['validation_commands'] = ['run meaningful tests']
    task = _replan(tmp_path)._task_from_failure(_board(tmp_path), evidence['task'], evidence)
    assert task['validation_commands'] == ['python verify_greeter.py']
