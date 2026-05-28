from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_profiles import AgentLoopProfileRegistry
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
    JsonStore(validator).write(run_dir / "agent_loop_dispatch.json", dispatch, schema_name=None)
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
    summary = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source": source,
        "recorded_at": now_iso(),
        "evidence_refs": [
            str(run_dir / "agent_loop_dispatch.json"),
            str(run_dir / "capability_decisions.jsonl"),
            str(run_dir / "mcp_invocations.jsonl"),
            str(run_dir / "skill_invocations.jsonl"),
            str(run_dir / "user_progress.jsonl"),
        ],
    }
    JsonStore(validator).write(
        run_dir / "runtime_validation_matrix_evidence.json",
        summary,
        schema_name=None,
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
            "multi_agent_strategy": {"mode": "readonly_fanout"},
            "risk": "medium",
        },
    ]


def _run_id() -> str:
    safe = now_iso().replace(":", "").replace("+", "-").replace(".", "")
    return f"runtime-validation-matrix-{safe}"
