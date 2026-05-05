from pathlib import Path

from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


def validator() -> SchemaValidator:
    return SchemaValidator(Path.cwd() / "schemas")


def test_context_loader_includes_small_workspace_files_and_skips_secrets(tmp_path: Path) -> None:
    (tmp_path / ".agent" / "context").mkdir(parents=True)
    (tmp_path / "buggy_math.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "api.txt").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")

    context = ContextLoader(tmp_path, validator()).load()

    files = {item["path"]: item for item in context["workspace_files"]}
    assert files["buggy_math.py"]["content"] == "def add(a, b):\n    return a - b\n"
    assert files["notes.md"]["content"] == "# Notes\n"
    assert "secrets/api.txt" not in files
    assert ".env" not in files


def test_context_loader_includes_bounded_acceptance_failure_evidence(tmp_path: Path) -> None:
    schema_validator = validator()
    failures_dir = tmp_path / ".agent" / "acceptance" / "failures"
    failures_dir.mkdir(parents=True)
    store = JsonStore(schema_validator)
    for index in range(3):
        scenario = f"scenario_{index}"
        store.write(
            failures_dir / f"{scenario}.json",
            {
                "schema_version": "0.1.0",
                "evidence_id": f"acceptance-failure-{scenario}",
                "suite": "core",
                "scenario": scenario,
                "failure_summary": f"failure {index}",
                "acceptance_report": str(
                    tmp_path / ".agent" / "acceptance" / "acceptance_report.json"
                ),
                "summary_json": str(tmp_path / "summary.json"),
                "workspace": str(tmp_path / scenario),
                "transcript": str(tmp_path / scenario / "transcript.json"),
                "expected_file": str(tmp_path / scenario / "artifact.py"),
                "stdout_tail": "",
                "stderr_tail": "missing artifact",
                "reproduce": {
                    "cli": f"python -m agent_runtime /acceptance --scenario {scenario}",
                    "script": f"python scripts/real_model_acceptance.py --scenario {scenario}",
                },
                "promoted_task_id": f"task-000{index}",
                "created_at": f"2026-05-05T00:00:0{index}+08:00",
            },
            "acceptance_failure_evidence",
        )

    context = ContextLoader(
        tmp_path,
        schema_validator,
        acceptance_failure_limit=2,
    ).load()

    failures = context["acceptance_failures"]
    assert [failure["scenario"] for failure in failures] == ["scenario_1", "scenario_2"]
    assert failures[0]["evidence_path"] == ".agent/acceptance/failures/scenario_1.json"
    assert failures[1]["failure_summary"] == "failure 2"
    assert failures[1]["reproduce"]["cli"].endswith("--scenario scenario_2")
