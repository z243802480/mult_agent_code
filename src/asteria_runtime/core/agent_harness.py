from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CapabilityTool:
    name: str
    kind: str
    permission: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "permission": self.permission,
            "description": self.description,
        }


@dataclass(frozen=True)
class CapabilityManifest:
    modes: list[str]
    tools: list[CapabilityTool]
    boundaries: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": self.modes,
            "tools": [tool.to_dict() for tool in self.tools],
            "boundaries": self.boundaries,
        }

    def prompt_summary(self) -> str:
        tool_lines = [
            f"- {tool.name}: {tool.kind}, permission={tool.permission}"
            for tool in self.tools
        ]
        boundary_lines = [
            f"- {key}: {value}" for key, value in sorted(self.boundaries.items())
        ]
        return "\n".join(
            [
                "Available modes: " + ", ".join(self.modes),
                "Available capabilities:",
                *tool_lines,
                "Runtime boundaries:",
                *boundary_lines,
            ]
        )


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    ok: bool
    summary: str
    status: str
    error: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "ok": self.ok,
            "summary": self.summary,
            "status": self.status,
            "error": self.error,
            "artifact_refs": self.artifact_refs,
            "file_changes": self.file_changes,
            "telemetry": self.telemetry,
            "data": self.data,
        }

    def model_summary(self) -> str:
        state = "ok" if self.ok else "failed"
        error = f"; error={self.error}" if self.error else ""
        files = ""
        if self.file_changes:
            changed = [
                str(change.get("path"))
                for change in self.file_changes[:3]
                if change.get("path")
            ]
            if changed:
                files = "; files=" + ", ".join(changed)
        return f"{self.tool_name} {state}: {self.summary}{error}{files}"


def tool_observation_dict(result: Any) -> dict[str, Any] | None:
    observation = getattr(result, "harness_observation", None)
    if isinstance(observation, ToolObservation):
        return observation.to_dict()
    if isinstance(observation, dict):
        return observation
    return None


def tool_observation_summary(result: Any) -> str | None:
    observation = getattr(result, "harness_observation", None)
    if isinstance(observation, ToolObservation):
        return observation.model_summary()
    if isinstance(observation, dict):
        tool_name = str(observation.get("tool_name") or "tool")
        ok = bool(observation.get("ok"))
        state = "ok" if ok else "failed"
        summary = str(observation.get("summary") or "")
        error = f"; error={observation.get('error')}" if observation.get("error") else ""
        return f"{tool_name} {state}: {summary}{error}"
    return None


def harness_observation_record(
    *,
    task_id: str | None,
    stage: str | None,
    summary: str | None,
    observation: ToolObservation | dict[str, Any],
) -> dict[str, Any]:
    observation_dict = observation.to_dict() if isinstance(observation, ToolObservation) else observation
    return {
        "task_id": task_id,
        "stage": stage,
        "summary": summary or _observation_summary_from_dict(observation_dict),
        "observation": observation_dict,
    }


def load_harness_observations(run_dir: Path | None, *, limit: int = 12) -> list[dict[str, Any]]:
    if run_dir is None:
        return []
    path = run_dir / "user_progress.jsonl"
    if not path.exists():
        return []
    observations: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("channel") != "execution_chain":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        observation = data.get("observation") if isinstance(data, dict) else None
        if not isinstance(observation, dict):
            continue
        chain = event.get("execution_chain")
        task_id = chain[0] if isinstance(chain, list) and chain else None
        observations.append(
            harness_observation_record(
                task_id=task_id,
                stage=event.get("event_type"),
                summary=event.get("summary"),
                observation=observation,
            )
        )
    return observations[-limit:]


def _observation_summary_from_dict(observation: dict[str, Any]) -> str:
    tool_name = str(observation.get("tool_name") or "tool")
    state = "ok" if observation.get("ok") else "failed"
    summary = str(observation.get("summary") or "")
    error = f"; error={observation.get('error')}" if observation.get("error") else ""
    return f"{tool_name} {state}: {summary}{error}"


@dataclass(frozen=True)
class HarnessTurnEvent:
    turn_id: str
    run_id: str | None
    task_id: str | None
    event_type: str
    summary: str
    observation: ToolObservation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "summary": self.summary,
            "observation": self.observation.to_dict() if self.observation else None,
        }


class AgentHarness:
    """Builds the model-visible capability envelope for agent-led work."""

    def __init__(self, policy: dict[str, Any], tool_names: list[str] | None = None) -> None:
        self.policy = policy
        self.tool_names = sorted(tool_names or [])

    def capability_manifest(self, mode: str = "build") -> CapabilityManifest:
        permissions = self.policy.get("permissions") or {}
        protected_paths = self.policy.get("protected_paths") or []
        tools = self._default_tools(permissions)
        tools.extend(self._registered_tools(permissions))
        return CapabilityManifest(
            modes=["plan", "build", "review", "repair", "release"],
            tools=self._dedupe_tools(tools),
            boundaries={
                "active_mode": mode,
                "protected_paths": protected_paths,
                "network": "allow" if permissions.get("allow_network") else "ask_or_deny",
                "shell": "allow" if permissions.get("allow_shell") else "deny",
                "destructive_shell": "allow" if permissions.get("allow_destructive_shell") else "deny",
                "remote_push": "allow" if permissions.get("allow_remote_push") else "deny",
                "writes": "candidate_workspace_preferred",
                "budget": "runtime_enforced",
            },
        )

    def _default_tools(self, permissions: dict[str, Any]) -> list[CapabilityTool]:
        shell_permission = "ask" if permissions.get("allow_shell") else "deny"
        return [
            CapabilityTool("read_file", "read", "allow", "Read files inside the workspace."),
            CapabilityTool("search", "read", "allow", "Search workspace text and filenames."),
            CapabilityTool("edit_file", "write", "ask", "Create or modify workspace files."),
            CapabilityTool("shell", "execute", shell_permission, "Run non-destructive shell commands."),
            CapabilityTool("run_tests", "verify", shell_permission, "Run bounded local verification."),
            CapabilityTool("mcp", "external", "ask", "Use configured MCP tools when policy allows."),
            CapabilityTool("skill", "workflow", "allow", "Load task-specific workflow guidance."),
            CapabilityTool("subagent", "delegate", "ask", "Delegate bounded work to a child worker."),
        ]

    def _registered_tools(self, permissions: dict[str, Any]) -> list[CapabilityTool]:
        shell_like = {"run_command", "run_tests"}
        write_like = {"write_file", "apply_patch"}
        tools: list[CapabilityTool] = []
        for name in self.tool_names:
            if name in shell_like:
                permission = "ask" if permissions.get("allow_shell") else "deny"
                kind = "execute"
            elif name in write_like:
                permission = "ask"
                kind = "write"
            else:
                permission = "allow"
                kind = "read"
            tools.append(CapabilityTool(name, kind, permission))
        return tools

    def _dedupe_tools(self, tools: list[CapabilityTool]) -> list[CapabilityTool]:
        by_name: dict[str, CapabilityTool] = {}
        for tool in tools:
            by_name[tool.name] = tool
        return [by_name[name] for name in sorted(by_name)]


def observation_from_tool_result(
    *,
    tool_name: str,
    result: Any,
    telemetry: dict[str, Any] | None = None,
    file_changes: list[dict[str, Any]] | None = None,
    artifact_refs: list[str] | None = None,
) -> ToolObservation:
    data = getattr(result, "data", None)
    safe_data = _observation_data(data)
    return ToolObservation(
        tool_name=tool_name,
        ok=bool(getattr(result, "ok", False)),
        summary=str(getattr(result, "summary", "")),
        status=str(getattr(result, "status", "") or ("success" if getattr(result, "ok", False) else "failure")),
        error=getattr(result, "error", None),
        artifact_refs=artifact_refs or _artifact_refs(tool_name, safe_data),
        file_changes=file_changes or [],
        telemetry=telemetry or {},
        data=safe_data,
    )


def observation_from_exception(
    *,
    tool_name: str,
    exc: Exception,
    telemetry: dict[str, Any] | None = None,
    file_changes: list[dict[str, Any]] | None = None,
) -> ToolObservation:
    return ToolObservation(
        tool_name=tool_name,
        ok=False,
        summary=str(exc),
        status="failure",
        error=str(exc),
        file_changes=file_changes or [],
        telemetry=telemetry or {},
        data={"error_type": exc.__class__.__name__},
    )


def _observation_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if key not in {"content", "diff"}
    }


def _artifact_refs(tool_name: str, data: dict[str, Any]) -> list[str]:
    if tool_name == "write_file" and data.get("path"):
        return [str(data["path"])]
    changed_files = data.get("changed_files")
    if isinstance(changed_files, list):
        return [str(path) for path in changed_files]
    return []
