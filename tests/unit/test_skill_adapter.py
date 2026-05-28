import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.skill_adapter import SkillAdapter, SkillDiscovery, SkillRoot
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


class FailingSkill:
    def invoke(self, request: dict) -> dict:
        raise ValueError("argument schema mismatch")


def test_skill_discovery_loads_skill_md_contract(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "documents"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: documents",
                "description: Generate document artifacts",
                "parameters: title, outline",
                "artifacts: docx, pdf",
                "---",
                "",
                "# Documents",
            ]
        ),
        encoding="utf-8",
    )

    definitions = SkillDiscovery([tmp_path / "skills"]).discover()
    adapter = SkillAdapter.from_skill_roots([tmp_path / "skills"])

    assert definitions[0].name == "documents"
    assert definitions[0].parameter_contract == {"summary": "title, outline"}
    assert definitions[0].artifact_types == ["docx", "pdf"]
    assert adapter.catalog()[0]["description"] == "Generate document artifacts"


def test_skill_discovery_merges_global_and_workspace_scopes(tmp_path: Path) -> None:
    global_dir = tmp_path / "global" / "skills" / "documents"
    workspace_dir = tmp_path / "workspace" / ".asteria" / "skills" / "documents"
    research_dir = tmp_path / "global" / "skills" / "research"
    global_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    research_dir.mkdir(parents=True)
    (global_dir / "SKILL.md").write_text(
        "name: documents\ndescription: Global documents skill\n",
        encoding="utf-8",
    )
    (workspace_dir / "SKILL.md").write_text(
        "name: documents\ndescription: Workspace documents override\n",
        encoding="utf-8",
    )
    (research_dir / "SKILL.md").write_text(
        "name: research\ndescription: Global research skill\n",
        encoding="utf-8",
    )

    definitions = SkillDiscovery(
        [
            SkillRoot(tmp_path / "global" / "skills", scope="global"),
            SkillRoot(tmp_path / "workspace" / ".asteria" / "skills", scope="workspace"),
        ]
    ).discover()
    catalog = SkillAdapter.from_skill_roots(
        [
            SkillRoot(tmp_path / "global" / "skills", scope="global"),
            SkillRoot(tmp_path / "workspace" / ".asteria" / "skills", scope="workspace"),
        ]
    ).catalog()

    assert [definition.name for definition in definitions] == ["research", "documents"]
    assert definitions[0].scope == "global"
    assert definitions[1].scope == "workspace"
    assert definitions[1].description == "Workspace documents override"
    assert next(item for item in catalog if item["name"] == "documents")["scope"] == "workspace"


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


def test_skill_adapter_classifies_contract_failures(tmp_path: Path) -> None:
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

    result = SkillAdapter({"documents": FailingSkill()}).invoke(
        context=context,
        task=task,
        skill_name="documents",
        arguments={"title": "Quarterly"},
    )

    assert result.ok is False
    assert result.status == "contract_error"
    invocations = JsonlStore(validator).read_all(run_dir / "skill_invocations.jsonl", None)
    assert invocations[0]["status"] == "contract_error"


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
