from pathlib import Path

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
