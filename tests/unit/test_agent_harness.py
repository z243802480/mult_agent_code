import json

from asteria_runtime.core.agent_harness import (
    AgentHarness,
    load_harness_observations,
    observation_from_tool_result,
)
from asteria_runtime.tools.base import ToolResult


def test_agent_harness_builds_model_visible_capability_manifest() -> None:
    policy = {
        "permissions": {
            "allow_network": False,
            "allow_shell": True,
            "allow_destructive_shell": False,
            "allow_remote_push": False,
        },
        "protected_paths": [".env", "secrets/"],
    }

    manifest = AgentHarness(policy, tool_names=["apply_patch", "read_file", "run_command"]).capability_manifest(
        mode="build"
    )

    data = manifest.to_dict()
    tools = {tool["name"]: tool for tool in data["tools"]}
    assert data["boundaries"]["active_mode"] == "build"
    assert data["boundaries"]["protected_paths"] == [".env", "secrets/"]
    assert data["boundaries"]["destructive_shell"] == "deny"
    assert tools["apply_patch"]["kind"] == "write"
    assert tools["apply_patch"]["permission"] == "ask"
    assert tools["run_command"]["kind"] == "execute"
    assert "Available modes" in manifest.prompt_summary()


def test_tool_observation_summarizes_result_for_model_loop() -> None:
    result = ToolResult(
        ok=True,
        summary="Wrote src/app.py",
        data={"path": "src/app.py", "content": "secret body is not copied"},
    )

    observation = observation_from_tool_result(tool_name="write_file", result=result)

    assert observation.ok is True
    assert observation.artifact_refs == ["src/app.py"]
    assert "content" not in observation.data
    assert observation.model_summary() == "write_file ok: Wrote src/app.py"


def test_load_harness_observations_reads_execution_chain_events(tmp_path) -> None:
    progress = tmp_path / "user_progress.jsonl"
    progress.write_text(
        "\n".join(
            [
                json.dumps({"channel": "tool", "event_type": "tool_output"}),
                json.dumps(
                    {
                        "channel": "execution_chain",
                        "event_type": "tool_observation",
                        "summary": "run_command failed: tests failed",
                        "execution_chain": ["task-1", "tool_observation"],
                        "data": {
                            "observation": {
                                "tool_name": "run_command",
                                "ok": False,
                                "summary": "tests failed",
                                "status": "failure",
                            }
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    observations = load_harness_observations(tmp_path)

    assert observations == [
        {
            "task_id": "task-1",
            "stage": "tool_observation",
            "summary": "run_command failed: tests failed",
            "observation": {
                "tool_name": "run_command",
                "ok": False,
                "summary": "tests failed",
                "status": "failure",
            },
        }
    ]
