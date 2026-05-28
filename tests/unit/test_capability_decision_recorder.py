from pathlib import Path

from asteria_runtime.core.capability_decision_recorder import CapabilityDecisionRecorder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_capability_decision_recorder_records_mcp_and_skill_decisions(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    recorder = CapabilityDecisionRecorder()

    mcp_decision = recorder.decide_mcp(
        "mcp",
        task={"task_id": "task-1", "task_kind": "research"},
        context=context,
        mcp_invocation_id="mcp-0001",
    )
    skill_decision = recorder.decide_skill(
        "documents",
        task={
            "task_id": "task-2",
            "task_kind": "document",
            "allowed_skills": ["documents"],
        },
        context=context,
        skill_invocation_id="skill-0001",
    )

    assert mcp_decision["capability_type"] == "mcp"
    assert mcp_decision["decision"] == "ask"
    assert mcp_decision["reason"]
    assert skill_decision["capability_type"] == "skill"
    assert skill_decision["decision"] == "allow"

    decisions = JsonlStore(validator).read_all(
        tmp_path / "capability_decisions.jsonl",
        schema_name=None,
    )
    assert [item["capability_type"] for item in decisions] == ["mcp", "skill"]
    assert decisions[0]["mcp_invocation_id"] == "mcp-0001"
    assert decisions[1]["skill_invocation_id"] == "skill-0001"
    assert all(item["decision"]["reason"] for item in decisions)

    progress = JsonlStore(validator).read_all(
        tmp_path / "user_progress.jsonl",
        "user_progress_event",
    )
    assert [(event["channel"], event["event_type"]) for event in progress] == [
        ("permission", "permission_decision"),
        ("permission", "permission_decision"),
    ]
    assert progress[0]["data"]["capability_decision"]["capability_type"] == "mcp"


def test_capability_decision_recorder_denies_unlisted_skill(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "auto", "protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )

    decision = CapabilityDecisionRecorder().decide_skill(
        "spreadsheets",
        task={
            "task_id": "task-1",
            "task_kind": "spreadsheet",
            "allowed_skills": ["documents"],
        },
        context=context,
        skill_invocation_id="skill-0001",
    )

    assert decision["decision"] == "deny"
    assert decision["allowed"] is False
    assert "task capability contract" in decision["reason"]
