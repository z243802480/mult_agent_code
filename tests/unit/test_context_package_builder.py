import json
from pathlib import Path

from agent_runtime.core.context_package_builder import ContextPackageBuilder
from agent_runtime.core.context_mount_builder import ContextMountBuilder
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_context_package_builder_loads_slices_from_mount_refs(tmp_path: Path) -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    run_dir = tmp_path / ".agent" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("root guidance", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "notes.py").write_text("VALUE = 1\n", encoding="utf-8")
    (run_dir / "goal_spec.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "goal_id": "goal-0001",
                "original_goal": "build notes",
                "normalized_goal": "Build notes",
                "goal_type": "software_tool",
                "assumptions": [],
                "constraints": ["local only"],
                "non_goals": [],
                "expanded_requirements": [],
                "target_outputs": ["python_module"],
                "definition_of_done": ["tests pass"],
                "verification_strategy": ["pytest"],
                "budget": {},
            }
        ),
        encoding="utf-8",
    )
    _append_jsonl(
        run_dir / "artifacts.jsonl",
        {
            "schema_version": "0.1.0",
            "artifact_id": "artifact-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "type": "source_file",
            "path": "src/notes.py",
            "created_by": "CoderAgent",
            "summary": "notes module",
            "created_at": "2026-05-13T10:00:00+08:00",
        },
    )
    _append_jsonl(
        run_dir / "task_failures.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "failure-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "phase": "verification",
            "failure_type": "test_failure",
            "summary": "pytest failed",
            "task_status": "blocked",
            "contract_check": {"ok": False},
            "tool_failures": [],
            "verification_failures": [],
            "recommendations": ["repair notes"],
            "created_at": "2026-05-13T10:01:00+08:00",
        },
    )
    _append_jsonl(
        run_dir / "decisions.jsonl",
        {
            "schema_version": "0.1.0",
            "decision_id": "decision-0001",
            "status": "resolved",
            "question": "Use local files?",
            "recommended_option_id": "option-1",
            "options": [{"option_id": "option-1", "label": "Yes", "tradeoff": "simple"}],
            "default_option_id": "option-1",
            "impact": {"scope": "low", "budget": "low", "risk": "low", "quality": "low"},
            "selected_option_id": "option-1",
            "created_at": "2026-05-13T10:02:00+08:00",
            "resolved_at": "2026-05-13T10:03:00+08:00",
            "metadata": {"task_id": "task-0001"},
        },
    )
    _append_jsonl(
        run_dir / "validation_results.jsonl",
        {
            "schema_version": "0.1.0",
            "validation_result_id": "validation-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "tool_name": "run_command",
            "command": "pytest tests/test_notes.py",
            "status": "failed",
            "summary": "pytest failed",
            "error": "nonzero_exit",
            "data": {"exit_code": 1},
            "created_at": "2026-05-13T10:04:00+08:00",
        },
    )
    _append_jsonl(
        run_dir / "runtime_requests.jsonl",
        {
            "schema_version": "0.1.0",
            "runtime_request_id": "runtime-request-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "request_type": "scope_expansion",
            "risk": "medium",
            "reason": "Need docs/notes.md",
            "details": {"write_scope": ["docs/notes.md"]},
            "status": "decision_created",
            "decision_id": "decision-0001",
            "created_at": "2026-05-13T10:05:00+08:00",
        },
    )
    _append_jsonl(
        run_dir / "workers.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "agent_id": "CoderAgent",
            "runtime_profile_id": "runtime-profile-0001",
            "status": "failed",
            "started_at": "2026-05-13T10:06:00+08:00",
            "ended_at": "2026-05-13T10:07:00+08:00",
            "summary": "Worker failed merge gate.",
        },
    )
    _append_jsonl(
        run_dir / "worker_results.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_result_id": "worker-result-0001",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "status": "failed",
            "artifact_refs": ["artifact-0001"],
            "validation_refs": ["validation-0001"],
            "failure_evidence_refs": ["failure-0001"],
            "cost": {"model_calls": 1, "tool_calls": 2},
            "summary": "Merge gate blocked promotion.",
        },
    )
    _append_jsonl(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-execution-0001",
            "run_id": "run-0001",
            "task_id": "task-0001",
            "status": "blocked",
            "summary": "Merge gate blocked promotion.",
            "failure_type": "merge_gate",
            "task": {},
            "action": {},
            "candidate": {},
            "contract_check": {
                "ok": True,
                "merge_gate": {
                    "ok": False,
                    "promotable_files": [],
                    "violations": ["changed files outside write_scope: docs/notes.md"],
                },
            },
            "tool_results": [],
            "verification_results": [],
            "created_at": "2026-05-13T10:08:00+08:00",
        },
    )
    task = {
        "task_id": "task-0001",
        "title": "Implement notes",
        "description": "Implement the notes module.",
        "acceptance": ["module exists"],
        "task_kind": "report",
        "read_scope": ["src/"],
        "write_scope": [],
        "parallel_safety": "readonly",
        "context_requirements": {
            "mount_type": "summary_context",
            "include_artifacts": True,
            "include_failures": True,
            "include_decisions": True,
            "include_validation": True,
            "recent_event_count": 0,
        },
    }
    mount = ContextMountBuilder("run-0001").build(
        task,
        artifact_refs=["artifact-0001"],
        failure_evidence_refs=["failure-0001"],
        decision_refs=["decision-0001"],
        validation_refs=["validation-0001"],
    )
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-0001",
        policy={"protected_paths": []},
        validator=validator,
    )

    package = ContextPackageBuilder(validator).build(context, task, mount.to_dict())

    assert package["root_guidance"]["content"] == "root guidance"
    assert package["goal_brief"]["normalized_goal"] == "Build notes"
    assert package["task_brief"]["task_id"] == "task-0001"
    assert package["read_scope_files"][0]["path"] == "src/notes.py"
    assert package["read_scope_files"][0]["content"]["text"] == "VALUE = 1\n"
    assert package["artifacts"][0]["content"]["text"] == "VALUE = 1\n"
    assert package["failures"][0]["summary"] == "pytest failed"
    assert package["decisions"][0]["selected_option_id"] == "option-1"
    assert package["validations"][0]["validation_result_id"] == "validation-0001"
    assert package["validations"][0]["error"] == "nonzero_exit"
    assert package["runtime_requests"][0]["runtime_request_id"] == "runtime-request-0001"
    assert package["worker_results"][0]["runtime_profile_id"] == "runtime-profile-0001"
    assert package["worker_results"][0]["failure_evidence_refs"] == ["failure-0001"]
    assert package["merge_gate_evidence"][0]["merge_gate"]["ok"] is False


def _append_jsonl(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
