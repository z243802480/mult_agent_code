from __future__ import annotations

from asteria_runtime.core.agent_loop_profiles import AgentLoopProfileRegistry


def test_agent_loop_profile_registry_matches_research_task() -> None:
    profile = AgentLoopProfileRegistry().for_task(
        {"task_id": "task-1", "task_kind": "research", "allowed_tools": ["read_file"]},
        permission_mode="reviewed_auto",
    )

    assert profile["loop_profile_id"] == "research"
    assert profile["intent"] == "research_goal"
    assert profile["capability_invocation_policy"]["allow_mcp"] is True
    assert profile["output_contract"]["artifact"] == "research_summary"
    assert profile["validation_contract"]["minimum_evidence_refs"] == 1
    assert profile["registered_capabilities"][0]["capability_id"] == "research.sources"


def test_agent_loop_profile_registry_matches_brainstorm_task() -> None:
    profile = AgentLoopProfileRegistry().for_task(
        {"task_id": "task-1", "task_kind": "brainstorm"},
        permission_mode="auto",
    )

    assert profile["loop_profile_id"] == "brainstorm"
    assert profile["capability_invocation_policy"]["tool_permissions"]["write"] == "deny"
    assert profile["output_contract"]["artifact"] == "brainstorm_options"
    assert "on_write_requested" in profile["failure_recovery"]
    assert profile["registered_capabilities"][0]["entrypoint"] == "asteria brainstorm"


def test_agent_loop_profile_registry_matches_multi_agent_strategy() -> None:
    profile = AgentLoopProfileRegistry().for_task(
        {
            "task_id": "task-1",
            "task_kind": "implementation",
            "expected_changed_files": ["a.py", "b.py"],
            "multi_agent_strategy": {"mode": "disjoint_write_workers"},
        },
        permission_mode="reviewed_auto",
    )

    assert profile["loop_profile_id"] == "multi_agent"
    assert profile["parallelism"] == "bounded_workers"
    assert profile["validation_contract"]["requires_merge_gate"] is True
    assert profile["registered_capabilities"][0]["capability_id"] == "multi_agent.workers"


def test_agent_loop_profile_registry_dispatches_plan() -> None:
    dispatch = AgentLoopProfileRegistry().dispatch_plan(
        [
            {"task_id": "task-1", "task_kind": "research"},
            {"task_id": "task-2", "task_kind": "brainstorm"},
            {
                "task_id": "task-3",
                "task_kind": "implementation",
                "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            },
        ],
        permission_mode="reviewed_auto",
    )

    assert dispatch["primary_loop_profile_id"] == "multi_agent"
    assert dispatch["profile_counts"] == {
        "research": 1,
        "brainstorm": 1,
        "multi_agent": 1,
    }
    assert [
        item["loop_profile_id"]
        for item in dispatch["task_dispatch"]
    ] == ["research", "brainstorm", "multi_agent"]
    assert dispatch["task_dispatch"][0]["capability_invocation_policy"]["intent"] == (
        "research_goal"
    )
    assert dispatch["task_dispatch"][2]["output_contract"]["artifact"] == (
        "multi_agent_execution_summary"
    )


def test_agent_loop_profile_registry_uses_task_local_capability_catalogs() -> None:
    dispatch = AgentLoopProfileRegistry().dispatch_plan(
        [
            {
                "task_id": "task-1",
                "task_kind": "diagnostic",
                "risk": "medium",
                "allowed_mcp": ["runtime_matrix/echo"],
                "mcp_servers": [{"name": "runtime_matrix", "tools": ["echo"]}],
            }
        ],
        permission_mode="reviewed_auto",
    )

    entries = {
        (item["capability_type"], item["name"]): item
        for item in dispatch["task_dispatch"][0]["capability_catalog"]["entries"]
    }
    assert entries[("mcp", "runtime_matrix/echo")]["selection_state"] == "selected"
