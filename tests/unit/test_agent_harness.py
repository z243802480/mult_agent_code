import json
from pathlib import Path

from asteria_runtime.core.agent_harness import (
    AgentHarness,
    append_harness_observations,
    load_harness_observations,
    observation_from_tool_result,
    observation_next_action_plan,
    persist_observation_next_action_plan,
    refresh_tool_observation_plan,
    tool_observation_action_options,
)
from asteria_runtime.storage.schema_validator import SchemaValidator
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

    manifest = AgentHarness(
        policy, tool_names=["apply_patch", "read_file", "run_command"]
    ).capability_manifest(mode="build")

    data = manifest.to_dict()
    tools = {tool["name"]: tool for tool in data["tools"]}
    direct_tools = {tool["name"]: tool for tool in data["direct_tools"]}
    assert data["boundaries"]["active_mode"] == "build"
    assert data["boundaries"]["protected_paths"] == [".env", "secrets/"]
    assert data["boundaries"]["destructive_shell"] == "deny"
    assert tools["apply_patch"]["kind"] == "write"
    assert tools["apply_patch"]["permission"] == "ask"
    assert direct_tools["apply_patch"]["permission_state"] == "ask"
    assert tools["run_command"]["kind"] == "execute"
    assert data["deferred_tools"][0]["name"] == "tool_search"
    assert data["mcp_tools"][0]["permission_state"] == "ask"
    assert data["skills"][0]["name"] == "skill"
    assert data["subagents"][0]["name"] == "subagent"
    assert {item["name"] for item in data["verification"]} >= {"run_tests", "merge_gate"}
    assert "Available modes" in manifest.prompt_summary()
    assert "Direct tools" in manifest.prompt_summary()


def test_agent_harness_builds_prompt_envelope_without_full_prompt_body() -> None:
    policy = {
        "permissions": {
            "allow_network": False,
            "allow_shell": False,
            "allow_destructive_shell": False,
            "allow_remote_push": False,
        },
        "protected_paths": [".env"],
        "budgets": {"max_model_calls_per_goal": 60},
    }

    envelope = AgentHarness(policy, tool_names=["read_file"]).prompt_envelope(
        run_id="run-1",
        mode="plan",
        project_guidance="Project rules and boundaries.",
        project_guidance_refs=["AGENTS.md"],
    )

    data = envelope.to_dict()
    section_names = {section["name"] for section in data["sections"]}
    assert section_names >= {
        "identity",
        "operating_contract",
        "project_guidance",
        "capability_manifest",
        "tool_policy",
        "safety_envelope",
        "failure_repair",
        "delegation_contract",
        "context_compaction",
        "user_communication",
    }
    project = next(section for section in data["sections"] if section["name"] == "project_guidance")
    assert project["evidence_refs"] == ["AGENTS.md"]
    assert project["content_hash"].startswith("sha256:")
    assert "content" not in project
    assert data["capability_manifest"]["direct_tools"]
    assert data["content_hash"].startswith("sha256:")


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


def test_failed_tool_observation_builds_explicit_action_options() -> None:
    actions = tool_observation_action_options(
        [
            {
                "tool_name": "run_command",
                "ok": False,
                "error_class": "verification_failed",
                "next_hint": "diagnose_then_repair_replan_ask_or_stop",
            }
        ]
    )

    assert [item["action"] for item in actions] == [
        "diagnose",
        "repair",
        "replan",
        "ask",
        "stop",
    ]
    assert all(item["tool_name"] == "run_command" for item in actions)


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


def test_observation_next_action_plan_exposes_blockers_and_evidence() -> None:
    plan = observation_next_action_plan(
        [
            {
                "tool_name": "run_command",
                "ok": False,
                "summary": "pytest failed",
                "error_class": "verification_failed",
                "next_hint": "diagnose_then_repair_replan_ask_or_stop",
                "artifact_refs": [".asteria/runs/run-1/tool_observations.jsonl"],
            }
        ]
    )

    assert plan["failed_observation_count"] == 1
    assert plan["blockers"] == ["run_command: pytest failed"]
    assert plan["evidence_refs"] == [".asteria/runs/run-1/tool_observations.jsonl"]
    assert {action["action"] for action in plan["actions"]} >= {
        "diagnose",
        "repair",
        "replan",
        "ask",
        "stop",
    }


def test_append_harness_observations_updates_runtime_context() -> None:
    result = ToolResult(ok=False, summary="tests failed", error="nonzero_exit")
    observation = observation_from_tool_result(tool_name="run_command", result=result)
    setattr(result, "harness_observation", observation)
    runtime_context: dict = {}

    appended = append_harness_observations(
        runtime_context,
        task_id="task-1",
        stage="verification",
        results=[result],
    )
    plan = refresh_tool_observation_plan(
        runtime_context,
        [
            {
                "tool_name": "run_command",
                "ok": False,
                "summary": "tests failed",
                "error_class": "nonzero_exit",
                "next_hint": "diagnose_then_repair_replan_ask_or_stop",
            }
        ],
    )

    assert appended[0]["task_id"] == "task-1"
    assert runtime_context["harness_observations"][0]["stage"] == "verification"
    assert plan["failed_observation_count"] == 1
    assert {action["action"] for action in runtime_context["tool_observation_actions"]} >= {
        "diagnose",
        "repair",
        "replan",
        "ask",
        "stop",
    }


def test_refresh_tool_observation_plan_uses_harness_observations_by_default() -> None:
    result = ToolResult(ok=False, summary="tests failed", error="nonzero_exit")
    observation = observation_from_tool_result(tool_name="run_command", result=result)
    setattr(result, "harness_observation", observation)
    runtime_context: dict = {}
    append_harness_observations(
        runtime_context,
        task_id="task-1",
        stage="verification",
        results=[result],
    )

    plan = refresh_tool_observation_plan(runtime_context)

    assert plan["failed_observation_count"] == 1
    assert plan["blockers"] == ["run_command: tests failed"]
    assert {action["action"] for action in plan["actions"]} >= {
        "diagnose",
        "repair",
        "replan",
        "ask",
        "stop",
    }


def test_persist_observation_next_action_plan_writes_jsonl(tmp_path) -> None:
    validator = SchemaValidator(Path("schemas"))
    plan = observation_next_action_plan(
        [
            {
                "tool_name": "run_command",
                "ok": False,
                "summary": "verification did not pass",
                "error_class": "nonzero_exit",
                "next_hint": "diagnose_then_repair_replan_ask_or_stop",
                "evidence_refs": ["tool_calls.jsonl"],
            }
        ]
    )

    record = persist_observation_next_action_plan(
        run_dir=tmp_path,
        validator=validator,
        plan=plan,
        run_id="run-1",
        task_id="task-1",
        trigger="unit",
    )

    assert record is not None
    assert record["observation_plan_id"] == "observation-plan-0001"
    assert record["recommended_route"] == "repair"
    assert (tmp_path / "observation_plans.jsonl").exists()
