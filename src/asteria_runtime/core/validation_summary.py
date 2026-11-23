"""Project declared method results without erasing or reinterpreting execution history."""

from collections import Counter
from pathlib import Path

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.review_focus import scoped_observations
from asteria_runtime.core.task_verification import (
    VERIFICATION_TOOLS,
    declared_commands,
    declared_observations,
    has_declared_checks,
)
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def load_validation_conclusion(root: Path, run_dir: Path, validator: SchemaValidator) -> dict:
    """Current means method membership and per-task order, not current artifact bytes.

    The completion contract's existing selection/freshness rules remain authoritative.
    This read-only result neither grants acceptance nor certifies requirement coverage.
    """
    jsonl = JsonlStore(validator)

    def rows(name: str, schema: str) -> list[dict]:
        path = run_dir / name
        return jsonl.read_all(path, schema) if path.exists() else []

    validations = rows("validation_results.jsonl", "validation_result")
    calls = rows("tool_calls.jsonl", "tool_call")
    checks = [c for c in calls if c.get("tool_name") in VERIFICATION_TOOLS]
    passed = sum(v.get("status") == "passed" for v in validations) + sum(
        c.get("status") == "success" for c in checks
    )
    failed = sum(v.get("status") == "failed" for v in validations) + sum(
        c.get("status") != "success" for c in checks
    )
    total = len(validations) + len(checks)
    history = {
        "status": "not_recorded" if not total else "failed" if failed else "passed",
        "total": total,
        "passed": passed,
        "failed": failed,
        "scope": "all_recorded_results_and_invocations_not_test_cases",
    }
    refs = [
        (run_dir / name).relative_to(root).as_posix()
        for name, present in (
            ("validation_results.jsonl", validations),
            ("tool_calls.jsonl", checks),
        )
        if present
    ]
    result = {
        **history,
        "scope": "historical_records_only",
        "history": history,
        "summary": f"Historical execution records: {passed}/{total} passed, {failed} failed; "
        "not a current artifact or requirement coverage judgment.",
        "validation_result_count": len(validations),
        "verification_command_count": len(checks),
        "artifact_freshness": "unassessed",
        "requirement_coverage": "unassessed",
        "evidence_refs": refs,
    }
    board_path = run_dir / "task_plan.json"
    board = JsonStore(validator).read(board_path, "task_board") if board_path.exists() else {}
    tasks = [
        t for t in board.get("tasks", []) if t.get("status") not in {"discarded", "superseded"}
    ]
    if not any(
        isinstance(t.get("verification_policy"), dict)
        and t["verification_policy"].get("command_source") == "planner_task"
        for t in tasks
    ):
        return result

    records = rows("tool_observations.jsonl", "tool_observation")
    own = [r for r in records if r.get("run_id") == run_dir.name]
    scoped = scoped_observations(run_dir.name, records)
    identities = Counter(t.get("task_id") for t in tasks)
    call_ids = Counter(c.get("tool_call_id") for c in calls if c.get("run_id") == run_dir.name)
    indexed = {c.get("tool_call_id"): c for c in calls if c.get("run_id") == run_dir.name}
    passed = failed = total = 0
    unassessed = []
    for task in tasks:
        task_id = task.get("task_id")
        selected = [r for r in scoped if r.get("task_id") == task_id]
        raw = [r for r in own if r.get("task_id") == task_id]
        policy = task.get("verification_policy") or {}
        try:
            commands = declared_commands(task)
            contract = (
                has_declared_checks(task)
                and isinstance(task.get("validation_commands", []), list)
                and all(isinstance(c, str) for c in task.get("validation_commands", []))
            )
        except (TypeError, AttributeError):
            commands, contract = [], False
        valid = (
            bool(task_id)
            and identities[task_id] == 1
            and contract
            and len(selected) == len(raw)
            and ("commands" not in policy or policy["commands"] == commands)
        )
        observations = []
        for record in selected:
            call = indexed.get(record["tool_call_id"], {})
            body = record["observation"]
            if (
                call_ids[record["tool_call_id"]] != 1
                or any(call.get(k) != record.get(k) for k in ("task_id", "tool_name"))
                # Call outcomes distinguish denied/timeout; observations use failure.
                # Compare success facts, never require identical phase-specific labels.
                or (call.get("status") == "success") != record.get("ok")
                or any(body.get(k) != record.get(k) for k in ("tool_name", "ok", "status"))
                or not isinstance(body.get("data", {}), dict)
            ):
                valid = False
                break
            try:
                observations.append(ToolObservation(**body))
            except (TypeError, ValueError):
                valid = False
                break
        if not valid:
            unassessed.append(task_id or "unknown")
            continue
        current = declared_observations(task, observations, root)
        if not current:
            unassessed.append(task_id)
        for observation in current:
            ok = observation.ok and observation.status == "success"
            if observation.tool_name in VERIFICATION_TOOLS:
                code = observation.data.get("returncode")
                ok = ok and type(code) is int and code == 0
            total += 1
            passed += int(ok)
            failed += int(not ok)

    status = "failed" if failed else "not_recorded" if unassessed or not total else "passed"
    return {
        **result,
        "status": status,
        "total": total,
        "passed": passed,
        "failed": failed,
        "scope": "current_declared_methods_at_recorded_task_execution",
        "unassessed_task_ids": sorted(set(unassessed)),
        "summary": f"Recorded results for currently declared task checks: {passed}/{total} passed; "
        f"{len(set(unassessed))} task contract(s) unassessed. "
        f"Historical records retain {history['failed']} failure(s). "
        "Artifact freshness and requirement coverage are unassessed here.",
        "evidence_refs": [
            *refs,
            board_path.relative_to(root).as_posix(),
            *(
                [(run_dir / "tool_observations.jsonl").relative_to(root).as_posix()]
                if (run_dir / "tool_observations.jsonl").exists()
                else []
            ),
        ],
    }
