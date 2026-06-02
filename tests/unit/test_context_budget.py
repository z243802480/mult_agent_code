from __future__ import annotations

from asteria_runtime.core.context_budget import build_context_budget_snapshot


def test_context_budget_snapshot_attributes_subagent_child_context() -> None:
    repeated = "same worker evidence " * 20
    snapshot = build_context_budget_snapshot(
        policy={"context": {"model_context_window_tokens": 100_000}},
        run_id="run-1",
        task={
            "task_id": "task-1",
            "context_requirements": {"isolation_policy": "subagent_child_context"},
        },
        runtime_context={
            "runtime_profile_id": "runtime-profile-worker-0002",
            "context_mount": {
                "context_mount_id": "context-worker-0002",
                "includes": {
                    "isolation_policy": "subagent_child_context",
                    "parent_worker_invocation_id": "worker-0002",
                    "parent_runtime_profile_id": "runtime-profile-worker-0001",
                },
            },
            "context_package": {
                "goal_brief": {"normalized_goal": "ship runtime loop"},
                "task_brief": {"title": "child task"},
                "worker_results": [{"summary": repeated}, {"summary": repeated}],
            },
            "worker_topology": {
                "worker_kind": "subagent",
                "parent_worker_invocation_id": "worker-0002",
                "parent_runtime_profile_id": "runtime-profile-worker-0001",
            },
            "subagent_worker": {"worker_invocation_id": "worker-0002"},
            "parent_agent_loop_decision": {"decision_id": "agent-loop-decision-0001"},
        },
        runtime_profile_id="runtime-profile-worker-0002",
        context_mount_id="context-worker-0002",
    ).to_dict()

    assert snapshot["scope"] == "subagent_child"
    assert snapshot["worker_kind"] == "subagent"
    assert snapshot["parent_worker_invocation_id"] == "worker-0002"
    assert snapshot["sections"]["worker_results"] > 0
    assert snapshot["sections"]["subagent_worker"] > 0
    assert snapshot["duplicate_ref_count"] == 1
    assert snapshot["duplicate_estimated_tokens"] > 0
    assert snapshot["compact_boundary"]["estimated_tokens_before"] == snapshot["estimated_tokens"]


def test_context_budget_snapshot_marks_compact_boundary() -> None:
    large_text = "x" * 5000
    snapshot = build_context_budget_snapshot(
        policy={
            "context": {
                "model_context_window_tokens": 1000,
                "compaction_threshold": 0.5,
                "hard_stop_threshold": 0.8,
            }
        },
        run_id="run-1",
        task={"task_id": "task-1"},
        runtime_context={"context_package": {"read_scope_files": [{"content": large_text}]}},
        runtime_profile_id="runtime-profile-worker-0001",
        context_mount_id="context-worker-0001",
    ).to_dict()

    assert snapshot["pressure_status"] in {"hard_stop", "exceeded"}
    assert snapshot["compact_boundary"]["status"] == "required"
    assert "read_scope_files" in snapshot["compact_boundary"]["droppable_sections"]


def test_context_budget_snapshot_does_not_count_persisted_envelope_payload_duplicate() -> None:
    repeated = "persisted context payload " * 20
    snapshot = build_context_budget_snapshot(
        policy={"context": {"model_context_window_tokens": 100_000}},
        run_id="run-1",
        task={"task_id": "task-1"},
        runtime_context={
            "context_package": {
                "context_envelope_path": ".asteria/runs/run-1/context_envelope.json",
                "root_guidance": {"content": repeated},
                "context_envelope": {
                    "payload_hash": "sha256:context",
                    "payload": {"root_guidance": {"content": repeated}},
                },
            }
        },
        runtime_profile_id="runtime-profile-worker-0001",
        context_mount_id="context-worker-0001",
    ).to_dict()

    assert snapshot["duplicate_ref_count"] == 0
    assert snapshot["duplicate_estimated_tokens"] == 0


def test_context_budget_snapshot_ignores_repeated_metadata_refs() -> None:
    repeated_ref = ".asteria/runs/run-1/context_envelopes/context_envelope_task_child_worker_0002.json"
    repeated_content = "real duplicated context content " * 20
    snapshot = build_context_budget_snapshot(
        policy={"context": {"model_context_window_tokens": 100_000}},
        run_id="run-1",
        task={"task_id": "task-1"},
        runtime_context={
            "context_package": {
                "read_scope_files": [
                    {"path": repeated_ref, "content": repeated_content},
                    {"path": repeated_ref, "content": repeated_content},
                ],
                "evidence_scope": {
                    "evidence_refs": [repeated_ref, repeated_ref],
                    "runtime_profile_id": "runtime-profile-worker-0002",
                    "context_envelope_path": repeated_ref,
                },
            },
            "context_mount": {
                "context_mount_id": "context-mount-task-1",
                "refs": [repeated_ref, repeated_ref],
            },
        },
        runtime_profile_id="runtime-profile-worker-0001",
        context_mount_id="context-worker-0001",
    ).to_dict()

    assert snapshot["duplicate_ref_count"] == 1
    assert snapshot["duplicate_estimated_tokens"] > 0
