import json
from pathlib import Path

from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_persist_prompt_envelope_includes_agent_loop_dispatch_summary(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent_loop_dispatch.json").write_text(
        json.dumps(
            {
                "primary_loop_profile_id": "research",
                "profile_counts": {"research": 1},
                "task_dispatch": [
                    {
                        "task_id": "task-1",
                        "loop_profile_id": "research",
                        "dispatch_reason": "Collect bounded sources.",
                        "output_contract": {"artifact": "research_summary"},
                        "validation_contract": {"minimum_evidence_refs": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = persist_prompt_envelope(
        root=tmp_path,
        run_dir=run_dir,
        run_id="run-1",
        mode="execute",
        policy={"permissions": {}, "protected_paths": []},
        validator=SchemaValidator(Path.cwd() / "schemas"),
    )

    dispatch = record.data["capability_manifest"]["boundaries"]["agent_loop_dispatch"]
    assert dispatch["primary_loop_profile_id"] == "research"
    assert dispatch["task_dispatch"][0]["output_contract"]["artifact"] == "research_summary"
