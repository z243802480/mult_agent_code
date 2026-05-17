from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.core.execution_evidence_sink import ExecutionEvidenceSink
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass
class FakeToolResult:
    ok: bool
    summary: str
    error: str | None = None
    data: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def test_evidence_sink_records_validation_results_and_event(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    sink = ExecutionEvidenceSink(validator, actor="SinkTest")

    refs = sink.record_validation_results(
        context,
        _task(),
        [{"tool_name": "run_command", "args": {"command": "python -m pytest"}}],
        [FakeToolResult(ok=True, summary="passed", data={"stdout": "ok"})],
    )

    assert refs == ["validation-0001"]
    jsonl = JsonlStore(validator)
    validations = jsonl.read_all(tmp_path / "validation_results.jsonl", "validation_result")
    events = jsonl.read_all(tmp_path / "events.jsonl", "event")
    assert validations[0]["command"] == "python -m pytest"
    assert validations[0]["status"] == "passed"
    assert validations[0]["data"] == {"stdout": "ok"}
    assert events[-1]["type"] == "validation_results_recorded"
    assert events[-1]["actor"] == "SinkTest"


def test_evidence_sink_records_keep_experiment_and_artifact(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    sink = ExecutionEvidenceSink(validator, actor="SinkTest")
    tool_result = FakeToolResult(
        ok=True,
        summary="wrote file",
        data={"path": "src/tool.py", "backup_id": "backup-0001"},
    )

    sink.record_experiment(
        context=context,
        task=_task(),
        action={
            "summary": "Implement tool",
            "tool_calls": [{"tool_name": "write_file", "args": {"path": "src/tool.py"}}],
            "verification": [{"tool_name": "run_command", "args": {"command": "python tool.py"}}],
        },
        tool_results=[tool_result],
        verification_results=[FakeToolResult(ok=True, summary="verified")],
        decision="keep",
        reason="Verification passed.",
        promoted_files=["src/tool.py"],
    )

    jsonl = JsonlStore(validator)
    experiments = jsonl.read_all(tmp_path / "experiments.jsonl", "experiment")
    artifacts = jsonl.read_all(tmp_path / "artifacts.jsonl", "artifact")
    assert experiments[0]["candidate"]["changed_files"] == ["src/tool.py"]
    assert experiments[0]["candidate"]["backup_ids"] == ["backup-0001"]
    assert experiments[0]["candidate"]["promoted_files"] == ["src/tool.py"]
    assert experiments[0]["metrics_after"]["verification_pass_rate"] == 1.0
    assert artifacts[0]["path"] == "src/tool.py"
    assert artifacts[0]["type"] == "source_file"


def test_evidence_sink_records_task_failure(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    sink = ExecutionEvidenceSink(validator, actor="SinkTest")

    sink.record_task_failure(
        context=context,
        task=_task(),
        failure_type="contract_violation",
        summary="verification did not pass",
        contract_check={"violations": ["verification did not pass"]},
        verification_results=[FakeToolResult(ok=False, summary="failed", error="nonzero_exit")],
    )

    jsonl = JsonlStore(validator)
    failures = jsonl.read_all(tmp_path / "task_failures.jsonl", "task_failure_evidence")
    events = jsonl.read_all(tmp_path / "events.jsonl", "event")
    assert failures[0]["failure_type"] == "contract_violation"
    assert failures[0]["verification_failures"][0]["error"] == "nonzero_exit"
    assert events[-1]["type"] == "task_failure_recorded"
    assert events[-1]["actor"] == "SinkTest"


def test_evidence_sink_reads_runtime_refs(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    sink = ExecutionEvidenceSink(validator, actor="SinkTest")
    jsonl = JsonlStore(validator)
    jsonl.append(
        tmp_path / "decisions.jsonl",
        {
            "schema_version": "0.1.0",
            "decision_id": "decision-0001",
            "run_id": "run-1",
            "title": "Approve",
            "question": "Approve?",
            "status": "pending",
            "recommended_option_id": "approve",
            "options": [{"option_id": "approve", "label": "Approve", "tradeoff": "Continue."}],
            "default_option_id": "approve",
            "impact": {"scope": "low", "budget": "low", "risk": "low", "quality": "low"},
            "selected_option_id": None,
            "created_at": "2026-05-17T10:00:00+08:00",
            "resolved_at": None,
            "metadata": {"task_id": "task-0001"},
        },
        "decision_point",
    )
    sink.record_validation_results(
        context,
        _task(),
        [{"tool_name": "run_command", "args": {"command": "python -m pytest"}}],
        [FakeToolResult(ok=True, summary="passed")],
    )
    sink.record_task_failure(context, _task(), "exception", "failed")
    sink.record_experiment(
        context=context,
        task=_task(),
        action={"summary": "Implement tool", "tool_calls": [], "verification": []},
        tool_results=[
            FakeToolResult(
                ok=True,
                summary="wrote file",
                data={"path": "src/tool.py", "backup_id": "backup-0001"},
            )
        ],
        verification_results=[],
        decision="keep",
        reason="kept",
    )

    assert sink.decision_refs(context, "task-0001") == ["decision-0001"]
    assert sink.validation_refs(context, "task-0001") == ["validation-0001"]
    assert sink.task_failure_refs(context, "task-0001") == ["task-failure-0001"]
    assert sink.artifact_refs(context, "task-0001") == ["artifact-0001"]


def _context(tmp_path: Path, validator: SchemaValidator) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )


def _task() -> dict:
    return {
        "task_id": "task-0001",
        "title": "Implement tool",
        "status": "in_progress",
        "acceptance": ["tool works"],
    }
