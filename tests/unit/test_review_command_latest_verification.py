# -*- coding: utf-8 -*-
"""S101 (run-20261106-0001) regression: review judges verification on latest outcomes, not
cumulative attempt history. See review_command._latest_verification_rows for the failure it
closes: an append-only ledger makes every historical red permanent, so cumulative counting
routed contract-green runs into an unfalsifiable resume loop."""

from asteria_runtime.commands.review_command import (
    ReviewCommand,
    _latest_verification_rows,
    _verification_row_key,
)

from asteria_runtime.evaluation.verification_evidence import (
    final_round_verification,
    verification_item_kind,
)


def test_review_keeps_active_and_unattributed_verification_failures(tmp_path) -> None:
    command = ReviewCommand(tmp_path)
    evidence = [
        {
            "task_id": task_id,
            "verification_results": [{"ok": False, "data": {"command": f"verify {task_id}"}}],
        }
        for task_id in ("old", "active", "unknown")
    ]
    checks = command._deterministic_checks(
        {
            "tasks": [
                {"task_id": "active", "status": "blocked"},
                {"task_id": "old", "status": "discarded"},
            ]
        },
        {},
        {"task_execution_evidence": evidence},
    )

    assert checks["blocked_task_count"] == 1
    assert checks["command_verification_call_count"] == 2
    assert checks["command_verification_pass_rate"] == 0


def _call(tool_name: str, summary, status: str = "success", **extra) -> dict:
    row = {"tool_name": tool_name, "input_summary": summary, "status": status}
    row.update(extra)
    return row


def test_red_then_green_on_same_command_collapses_to_green() -> None:
    cmd = "python verify_daylight.py"
    rows = [
        _call("todo_write", {"items": 3}),
        _call("run_tests", {"command": cmd}, "failure"),
        _call("run_command", {"command": "dir /b"}, "failure"),
        _call("run_tests", {"command": cmd}, "success"),
    ]
    deduped = _latest_verification_rows(rows)
    # non-verification rows pass through; the red command row stays red (distinct command,
    # never superseded); the red→green pair collapses to the green at the red's position.
    assert len(deduped) == 3
    assert [r["status"] for r in deduped] == ["success", "success", "failure"]
    assert [r["tool_name"] for r in deduped] == ["todo_write", "run_tests", "run_command"]


def test_string_input_summary_after_schema_validation_is_usable_identity() -> None:
    cmd = "{'command': 'C:\\\\Python313\\\\python.exe verify_daylight.py'}"
    rows = [
        _call("run_tests", cmd, "failure"),
        _call("run_tests", cmd, "success"),
    ]
    deduped = _latest_verification_rows(rows)
    assert len(deduped) == 1
    assert deduped[0]["status"] == "success"


def test_readback_failure_superseded_by_read_of_same_path() -> None:
    rows = [
        _call("read_file", {"path": "result.txt"}, "failure"),
        _call("read_file", {"path": "AGENTS.md"}, "success"),
        _call("read_file", {"path": "result.txt"}, "success"),
    ]
    deduped = _latest_verification_rows(rows)
    assert len(deduped) == 2
    statuses = {r["input_summary"]["path"]: r["status"] for r in deduped}
    assert statuses == {"AGENTS.md": "success", "result.txt": "success"}


def test_row_without_extractable_identity_passes_through() -> None:
    row = {"tool_name": "run_command", "input_summary": {}, "status": "failure"}
    assert _verification_row_key(row) is None
    assert _latest_verification_rows([row]) == [row]


def test_final_round_verification_takes_latest_evidence_row_per_task() -> None:
    evidence = [
        {
            "task_id": "task-0001",
            "status": "done",
            "verification_results": [{"ok": True, "data": {"path": "a.md"}}],
        },
        {
            "task_id": "task-0002",
            "status": "blocked",
            "verification_results": [
                {"ok": False, "data": {"command": "python t.py", "requested_command": "python t.py"}}
            ],
        },
        {
            "task_id": "task-0002",
            "status": "done",
            "verification_results": [
                {"ok": True, "data": {"command": "python t.py", "requested_command": "python t.py"}}
            ],
        },
    ]
    final = final_round_verification(evidence)
    # task-0002's earlier blocked round is superseded by its done round.
    assert len(final) == 2
    assert all(item["ok"] for item in final)
    assert [verification_item_kind(item) for item in final] == ["readback", "command"]


def test_blocked_task_final_round_red_still_counts_as_red() -> None:
    evidence = [
        {
            "task_id": "task-0002",
            "status": "blocked",
            "verification_results": [
                {"ok": False, "data": {"command": "python t.py", "requested_command": "python t.py"}},
                {"ok": True, "data": {"path": "notes.md"}},
            ],
        },
    ]
    final = final_round_verification(evidence)
    kinds = [verification_item_kind(item) for item in final]
    assert kinds == ["command", "readback"]
    assert [item["ok"] for item in final] == [False, True]
