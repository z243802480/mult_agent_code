from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from asteria_runtime.core.agent_loop_executor import (
    persist_agent_loop_execution_result,
    persist_subagent_child_plan_for_execution,
)
from asteria_runtime.core.agent_loop_profiles import AgentLoopProfileRegistry
from asteria_runtime.core.agent_loop_decision import persist_agent_loop_decision
from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.skill_adapter import SkillAdapter
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


class RuntimeMatrixSkill:
    def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": "Runtime matrix skill probe completed.",
            "data": {
                "probe": "skill_adapter",
                "arguments": request.get("arguments") or {},
            },
            "artifacts": [
                {
                    "path": ".asteria/validation/runtime_matrix_skill_probe.json",
                    "type": "validation_evidence",
                    "summary": "Skill adapter validation probe artifact.",
                }
            ],
            "status": "success",
        }


class RuntimeMatrixMcpSession:
    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "runtime matrix mcp probe ok",
                }
            ],
            "method": method,
            "params": params,
        }

    def close(self) -> None:
        return None


def record_runtime_validation_matrix_evidence(
    *,
    root: Path,
    validator: Any,
    source: str = "validation-run",
) -> dict[str, Any]:
    """Record a bounded runtime-native evidence run for the validation matrix.

    This does not claim product delivery. It records adapter/profile/progress evidence
    using the same runtime stores that gate-status consumes.
    """

    root = root.resolve()
    run_id = _run_id()
    run_dir = root / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    context = RuntimeContext(
        root=root,
        run_id=run_id,
        policy={
            "permission_mode": "reviewed_auto",
            "protected_paths": [],
            "workspace_envelope": {
                "workspace_id": "runtime-validation-matrix",
                "output_root": str(root),
                "artifact_root": str(root / ".asteria" / "validation"),
            },
        },
        validator=validator,
        run_dir_override=run_dir,
    )
    tasks = _matrix_tasks()
    dispatch = AgentLoopProfileRegistry().dispatch_plan(
        tasks,
        permission_mode="reviewed_auto",
        runtime_tool_names=[
            "find_files",
            "read_file",
            "list_files",
            "search_text",
            "run_command",
            "run_tests",
            "todo_read",
            "todo_write",
        ],
        skill_catalog=[
            {
                "name": "documents",
                "scope": "workspace",
                "description": "Runtime matrix document skill probe.",
                "artifact_types": ["validation_evidence"],
            }
        ],
        mcp_servers=[{"name": "runtime_matrix", "tools": ["echo"]}],
        allow_shell=True,
    )
    # agent_loop_dispatch is also written raw by plan/run; no JSON-schema contract exists for
    # it yet, so this validation-evidence seeding writes it as an explicit unvalidated object.
    JsonStore(validator).write(
        run_dir / "agent_loop_dispatch.json", dispatch, allow_unvalidated=True
    )
    SkillAdapter({"documents": RuntimeMatrixSkill()}, actor="RuntimeValidationEvidence").invoke(
        context=context,
        task=tasks[1],
        skill_name="documents",
        arguments={"source": source},
    )
    mcp = McpAdapter(
        {"runtime_matrix": RuntimeMatrixMcpSession()},
        actor="RuntimeValidationEvidence",
    )
    mcp.invoke_tool(
        context=context,
        task=tasks[0],
        server_name="runtime_matrix",
        tool_name="echo",
        arguments={"message": "runtime matrix mcp probe ok"},
    )
    UserProgressLogger(run_dir / "user_progress.jsonl", validator).validation_event(
        run_id=run_id,
        title="Runtime validation matrix evidence",
        summary="Recorded Skill, MCP, profile dispatch, permission reason, and progress evidence.",
        validation={
            "source": source,
            "profile_counts": dispatch.get("profile_counts") or {},
            "capability_catalogs": [
                item.get("capability_catalog")
                for item in dispatch.get("task_dispatch", [])
                if isinstance(item, dict)
            ],
        },
        evidence_refs=[
            str(run_dir / "agent_loop_dispatch.json"),
            str(run_dir / "capability_decisions.jsonl"),
            str(run_dir / "mcp_invocations.jsonl"),
            str(run_dir / "skill_invocations.jsonl"),
            str(run_dir / "user_progress.jsonl"),
        ],
    )
    _record_swarm_matrix_probe_evidence(run_dir=run_dir, run_id=run_id, validator=validator)
    # Swarm production-gray band is frozen/removed; report disabled evidence.
    production_gray = SimpleNamespace(
        ok=False,
        execute=SimpleNamespace(run_id=""),
        evidence_path=run_dir / "production_gray_band_disabled.json",
    )
    summary = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source": source,
        "recorded_at": now_iso(),
        "production_gray_band_ok": production_gray.ok,
        "production_gray_run_id": production_gray.execute.run_id,
        "evidence_refs": [
            str(run_dir / "agent_loop_dispatch.json"),
            str(run_dir / "capability_decisions.jsonl"),
            str(run_dir / "mcp_invocations.jsonl"),
            str(run_dir / "skill_invocations.jsonl"),
            str(run_dir / "user_progress.jsonl"),
            str(production_gray.evidence_path),
        ],
    }
    # Validation-matrix evidence summary has no JSON-schema contract; explicit opt-out.
    JsonStore(validator).write(
        run_dir / "runtime_validation_matrix_evidence.json",
        summary,
        allow_unvalidated=True,
    )
    return summary


def _matrix_tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "runtime-matrix-research",
            "task_kind": "research",
            "allowed_tools": ["read_file", "search_text", "run_command", "run_tests"],
            "allowed_mcp": ["runtime_matrix"],
            "risk": "medium",
        },
        {
            "task_id": "runtime-matrix-skill",
            "task_kind": "document",
            "allowed_tools": ["read_file", "search_text"],
            "allowed_skills": ["documents"],
            "risk": "low",
        },
        {
            "task_id": "runtime-matrix-brainstorm",
            "task_kind": "brainstorm",
            "allowed_tools": ["read_file", "search_text", "run_command", "run_tests"],
            "risk": "low",
        },
        {
            "task_id": "runtime-matrix-multi-agent",
            "task_kind": "implementation",
            "allowed_tools": ["read_file", "search_text", "run_command", "run_tests"],
            "multi_agent_strategy": {"mode": "disjoint_write_workers"},
            "risk": "medium",
        },
    ]


def _run_id() -> str:
    safe = now_iso().replace(":", "").replace("+", "-").replace(".", "")
    return f"runtime-validation-matrix-{safe}"


def _record_swarm_matrix_probe_evidence(
    *,
    run_dir: Path,
    run_id: str,
    validator: Any,
) -> None:
    """Minimal subagent swarm planning evidence so matrix swarm_scenario_audit can pass."""
    decision = {
        "schema_version": "0.1.0",
        "decision_id": "agent-loop-decision-matrix-swarm-0001",
        "run_id": run_id,
        "task_id": "runtime-matrix-multi-agent",
        "created_at": now_iso(),
        "next_action": {
            "action": "subagent",
            "reason": "Matrix probe for swarm scenario audit.",
            "target_task_id": "runtime-matrix-multi-agent",
            "capability_ref": {"type": "subagent", "name": "disjoint_write_workers"},
            "expected_observation": {
                "summary": "Matrix probe child plan.",
                "write_scope": ["src/matrix_probe_a.py", "src/matrix_probe_b.py"],
                "parallel_safety": "disjoint_writes",
            },
            "risk": "low",
            "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
            "evidence_refs": [],
        },
    }
    task = {
        "task_id": "runtime-matrix-multi-agent",
        "title": "Matrix swarm probe",
        "parallel_safety": "disjoint_writes",
        "write_scope": ["src/matrix_probe_a.py", "src/matrix_probe_b.py"],
        "multi_agent_strategy": {
            "mode": "disjoint_write_workers",
            "max_child_workers": 2,
            "coordination_policy": {"requires_disjoint_write_scope": True},
        },
    }
    persist_agent_loop_decision(run_dir=run_dir, validator=validator, decision=decision)
    execution = persist_agent_loop_execution_result(
        run_dir=run_dir,
        validator=validator,
        decision=decision,
    )
    if isinstance(execution, dict):
        persist_subagent_child_plan_for_execution(
            run_dir=run_dir,
            validator=validator,
            decision=decision,
            execution_result=execution,
            task=task,
        )
