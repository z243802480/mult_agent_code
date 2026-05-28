import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.skill_adapter import SkillAdapter
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeSkill:
    def invoke(self, request: dict) -> dict:
        assert request["skill_name"] == "documents"
        return {
            "ok": True,
            "summary": "Document generated",
            "data": {"pages": 1},
            "artifacts": [
                {
                    "path": "out/report.docx",
                    "type": "document",
                    "summary": "Generated report",
                }
            ],
        }


def test_skill_adapter_records_decision_artifact_and_progress(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": [], "workspace_envelope": {"workspace_id": "workspace-1"}},
        validator=validator,
        run_dir_override=run_dir,
    )
    task = {
        "task_id": "task-1",
        "task_kind": "document",
        "allowed_skills": ["documents"],
    }

    result = SkillAdapter({"documents": FakeSkill()}).invoke(
        context=context,
        task=task,
        skill_name="documents",
        arguments={"title": "Quarterly"},
    )

    assert result.ok is True
    invocations = JsonlStore(validator).read_all(run_dir / "skill_invocations.jsonl", None)
    artifacts = JsonlStore(validator).read_all(run_dir / "artifacts.jsonl", "artifact")
    progress = JsonlStore(validator).read_all(
        run_dir / "user_progress.jsonl",
        "user_progress_event",
    )
    decisions = JsonlStore(validator).read_all(run_dir / "capability_decisions.jsonl", None)
    assert invocations[0]["skill_name"] == "documents"
    assert invocations[0]["artifact_refs"] == ["artifact-0001"]
    assert artifacts[0]["path"] == "out/report.docx"
    assert artifacts[0]["created_by"] == "SkillAdapter:documents"
    assert progress[-1]["event_type"] == "tool_output"
    assert progress[-1]["data"]["capability_type"] == "skill"
    assert progress[-1]["artifact_refs"] == ["artifact-0001"]
    assert decisions[0]["capability_type"] == "skill"
    assert decisions[0]["decision"]["reason"]


def test_skill_adapter_denies_unmatched_skill_and_redacts_arguments(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=run_dir,
    )
    task = {
        "task_id": "task-1",
        "task_kind": "document",
        "allowed_skills": ["documents"],
    }

    result = SkillAdapter({"spreadsheets": FakeSkill()}).invoke(
        context=context,
        task=task,
        skill_name="spreadsheets",
        arguments={"api_token": "secret"},
    )

    assert result.status == "denied"
    invocations = [
        json.loads(line)
        for line in (run_dir / "skill_invocations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert invocations[0]["arguments"] == {"api_token": "<redacted>"}
    assert invocations[0]["capability_decision"]["decision"] == "deny"
