from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAINSTREAM_AGENT_TOOL_PRIMITIVES = [
    "read_file",
    "write_file",
    "edit_file",
    "list_files",
    "glob",
    "grep",
    "search_text",
    "shell",
    "run_tests",
    "todo_read",
    "todo_write",
]

MODEL_TO_RUNTIME_TOOL_ALIASES = {
    "edit_file": "apply_patch",
    "glob": "find_files",
    "grep": "search_text",
    "shell": "run_command",
}

MODEL_TOOL_ARG_ALIASES = {
    "glob": {"pattern": "glob"},
}


@dataclass(frozen=True)
class ModelFacingTool:
    name: str
    kind: str
    permission: str
    adapter: str
    internal_tool: str | None
    parameter_contract: dict[str, Any]
    safety_notes: list[str]
    status: str = "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "permission": self.permission,
            "adapter": self.adapter,
            "internal_tool": self.internal_tool,
            "parameter_contract": self.parameter_contract,
            "safety_notes": self.safety_notes,
            "status": self.status,
        }


class ModelToolSurfaceAdapter:
    """Map internal runtime registry names to stable model-facing primitives."""

    def __init__(self, runtime_tool_names: list[str], *, allow_shell: bool = False) -> None:
        self.runtime_tools = set(runtime_tool_names)
        self.allow_shell = allow_shell

    def tools(self) -> list[ModelFacingTool]:
        definitions = [
            self._tool(
                "read_file",
                "read",
                "allow",
                "read_file",
                {"path": "workspace-relative file path", "encoding": "utf-8 by default"},
                ["Read only through PathGuard and protected path policy."],
            ),
            self._tool(
                "list_files",
                "read",
                "allow",
                "list_files",
                {"path": "workspace-relative directory path"},
                ["Prefer list_files before shell directory listing."],
            ),
            self._tool(
                "glob",
                "read",
                "allow",
                "find_files",
                {"pattern": "glob pattern", "path": "workspace-relative directory path"},
                ["Use for filename discovery; does not read file contents."],
            ),
            self._tool(
                "grep",
                "read",
                "allow",
                "search_text",
                {
                    "pattern": "literal text pattern",
                    "path": "workspace-relative file or directory path",
                    "case_sensitive": "boolean",
                },
                ["Use grep/search before shell pipelines for source inspection."],
            ),
            self._tool(
                "write_file",
                "write",
                "ask",
                "write_file",
                {"path": "workspace-relative file path", "content": "complete file content"},
                ["Creates backups and respects write scope."],
            ),
            self._tool(
                "edit_file",
                "write",
                "ask",
                "apply_patch",
                {"patch": "unified patch or structured patch payload"},
                ["Prefer edit_file/apply_patch for existing files."],
            ),
            self._tool(
                "shell",
                "execute",
                "ask" if self.allow_shell else "deny",
                "run_command",
                {"command": "bounded non-destructive command", "summary": "expected outcome"},
                ["Use dedicated read/search/edit/test tools before shell fallbacks."],
            ),
            self._tool(
                "run_tests",
                "verify",
                "ask" if self.allow_shell else "deny",
                ["run_tests", "run_command"],
                {"command": "test command or configured test suite"},
                ["Verification output is summarized; raw stdout remains evidence/Inspector."],
            ),
            self._tool(
                "todo_read",
                "planning",
                "allow",
                "todo_read",
                {},
                ["Reads run-local model planning state without mutating task_plan.json."],
            ),
            self._tool(
                "todo_write",
                "planning",
                "ask",
                "todo_write",
                {
                    "items": "ordered list of todo items with content/status/priority",
                    "reason": "why the model planning state changed",
                },
                ["Writes run-local model planning state; does not mutate task_plan.json."],
            ),
        ]
        return definitions

    def _tool(
        self,
        name: str,
        kind: str,
        permission: str,
        internal_tool: str | list[str],
        parameter_contract: dict[str, Any],
        safety_notes: list[str],
    ) -> ModelFacingTool:
        candidates = [internal_tool] if isinstance(internal_tool, str) else internal_tool
        resolved = next((item for item in candidates if item in self.runtime_tools), None)
        return ModelFacingTool(
            name=name,
            kind=kind,
            permission=permission if resolved else "deny",
            adapter="runtime_tool_registry" if resolved else "missing_internal_tool",
            internal_tool=resolved,
            parameter_contract=parameter_contract,
            safety_notes=safety_notes,
            status="available" if resolved else "missing",
        )


def model_tool_surface(
    runtime_tool_names: list[str],
    *,
    allow_shell: bool = False,
) -> list[dict[str, Any]]:
    return [
        tool.to_dict()
        for tool in ModelToolSurfaceAdapter(
            runtime_tool_names,
            allow_shell=allow_shell,
        ).tools()
    ]


def model_tools_available_for_task(
    runtime_tool_names: list[str],
    task: dict[str, Any],
    *,
    allow_shell: bool = False,
) -> list[str]:
    """Return model-facing tool names whose internal backend is allowed by the task."""

    allowed = set(str(tool) for tool in task.get("allowed_tools", []) if tool)
    available: list[str] = []
    for tool in model_tool_surface(runtime_tool_names, allow_shell=allow_shell):
        internal = tool.get("internal_tool")
        if tool.get("status") == "available" and internal in allowed:
            available.append(str(tool["name"]))
    return available


def model_tool_surface_for_task(
    runtime_tool_names: list[str],
    task: dict[str, Any],
    *,
    allow_shell: bool = False,
) -> dict[str, Any]:
    """Describe the task-scoped model-facing surface and internal registry mapping."""

    allowed = set(str(tool) for tool in task.get("allowed_tools", []) if tool)
    tools = []
    for tool in model_tool_surface(runtime_tool_names, allow_shell=allow_shell):
        internal = tool.get("internal_tool")
        task_allowed = bool(internal and internal in allowed)
        entry = dict(tool)
        entry["task_allowed"] = task_allowed
        if not task_allowed:
            entry["permission"] = "deny"
        tools.append(entry)
    return {
        "schema_version": "0.1.0",
        "adapter": "model_to_runtime_registry",
        "task_allowed_model_tools": [
            str(tool["name"])
            for tool in tools
            if tool.get("status") == "available" and tool.get("task_allowed")
        ],
        "tools": tools,
    }


def mcp_model_tools(
    discovered_tools: list[dict[str, Any]],
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    """Model-facing entries for discovered MCP tools, filtered by the task's MCP contract.

    ``discovered_tools`` come from ``McpAdapter.discover_tools()`` ({server, tool, model_name,
    description, input_schema}). The contract mirrors ``CapabilityDecisionRecorder`` for MCP:
    an empty ``allowed_mcp`` allows every configured tool; otherwise the server name OR the
    ``server/tool`` capability must be listed. Permission stays ``ask`` — the real allow/ask/deny
    happens at the call boundary inside ``McpAdapter.invoke_tool`` (``decide_mcp``).
    """
    allowed = {
        str(item)
        for item in (task.get("allowed_mcp") or task.get("allowed_mcp_tools") or [])
        if item
    }
    tools: list[dict[str, Any]] = []
    for entry in discovered_tools:
        server = str(entry.get("server") or "")
        tool = str(entry.get("tool") or "")
        if not server or not tool:
            continue
        model_name = str(entry.get("model_name") or f"mcp__{server}__{tool}")
        capability = f"{server}/{tool}"
        task_allowed = (not allowed) or (capability in allowed) or (server in allowed)
        schema = entry.get("input_schema")
        tools.append(
            {
                "name": model_name,
                "kind": "external",
                "permission": "ask" if task_allowed else "deny",
                "adapter": "mcp_protocol_session",
                "internal_tool": None,
                "parameter_contract": schema if isinstance(schema, dict) else {},
                "safety_notes": [
                    f"External MCP tool {capability}; allow/ask/deny is decided at the call "
                    "boundary via the MCP capability decision, and every call is audited."
                ],
                "status": "available" if task_allowed else "denied",
                "task_allowed": task_allowed,
                "server": server,
                "tool": tool,
                "description": str(entry.get("description") or ""),
            }
        )
    return tools


def skill_model_tools(
    discovered_skills: list[dict[str, Any]],
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    """Model-facing entries for discovered skills, filtered by the task's skill contract.

    ``discovered_skills`` come from ``SkillAdapter.discover_skills()`` ({name, model_name,
    description, parameter_contract}). The contract mirrors ``CapabilityDecisionRecorder`` for
    skills: an empty ``allowed_skills`` allows every discovered skill; otherwise the skill name
    must be listed. Permission stays ``ask`` — the real allow/ask/deny happens at the call
    boundary inside ``SkillAdapter.invoke`` (``decide_skill``). Invoking a skill loads its full
    procedure into context; the model then follows it with its existing tools.
    """
    allowed = {str(item) for item in (task.get("allowed_skills") or []) if item}
    tools: list[dict[str, Any]] = []
    for entry in discovered_skills:
        name = str(entry.get("name") or "")
        if not name:
            continue
        model_name = str(entry.get("model_name") or f"skill__{name}")
        task_allowed = (not allowed) or (name in allowed)
        contract = entry.get("parameter_contract")
        tools.append(
            {
                "name": model_name,
                "kind": "skill",
                "permission": "ask" if task_allowed else "deny",
                "adapter": "skill_workflow_artifact",
                "internal_tool": None,
                "parameter_contract": contract if isinstance(contract, dict) else {},
                "safety_notes": [
                    f"Skill {name}; invoking loads its full procedure into context. allow/ask/deny "
                    "is decided at the call boundary via the skill capability decision."
                ],
                "status": "available" if task_allowed else "denied",
                "task_allowed": task_allowed,
                "skill": name,
                "description": str(entry.get("description") or ""),
            }
        )
    return tools


def adapt_model_tool_call(
    call: dict[str, Any],
    runtime_tool_names: list[str],
) -> dict[str, Any]:
    """Translate a model-facing primitive call into an internal registry call."""

    raw_name = str(call.get("tool_name") or call.get("name") or call.get("tool") or "")
    runtime_names = set(runtime_tool_names)
    internal_name = MODEL_TO_RUNTIME_TOOL_ALIASES.get(raw_name, raw_name)
    if internal_name not in runtime_names:
        return dict(call)
    raw_args = call.get("args") or call.get("arguments") or {}
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    for model_arg, runtime_arg in MODEL_TOOL_ARG_ALIASES.get(raw_name, {}).items():
        if model_arg in args and runtime_arg not in args:
            args[runtime_arg] = args.pop(model_arg)
    adapted = dict(call)
    adapted["tool_name"] = internal_name
    adapted["args"] = args
    if raw_name != internal_name:
        adapted["model_tool_name"] = raw_name
        adapted["tool_surface_adapter"] = "model_to_runtime_registry"
    return adapted


def tool_surface_contract(
    runtime_tool_names: list[str],
    *,
    allow_shell: bool = False,
) -> dict[str, Any]:
    """Describe the distinction between runtime tools and model-facing tools.

    Asteria's current registry is an internal execution registry. It is not yet
    a Claude Code-style comprehensive model-facing tool surface.
    """

    runtime_names = sorted(set(runtime_tool_names))
    model_tools = model_tool_surface(runtime_names, allow_shell=allow_shell)
    missing = [tool["name"] for tool in model_tools if tool["status"] == "missing"]
    return {
        "schema_version": "0.1.0",
        "runtime_internal_registry": {
            "status": "implemented",
            "tool_count": len(runtime_names),
            "tools": runtime_names,
            "purpose": "runtime execution, evidence, permissions, and repair loop control",
        },
        "model_facing_standard_surface": {
            "status": "ready" if not missing else "partial",
            "target": "mainstream agent tool surface with dedicated file, search, edit, shell, todo, and adapter tools",
            "implemented_overlap": [
                tool["name"] for tool in model_tools if tool["status"] == "available"
            ],
            "missing_primitives": missing,
            "tools": model_tools,
        },
        "separation_rules": [
            "Do not treat internal runtime tools as a complete model-facing standard tool set.",
            "Expose safer dedicated read/list/search/edit primitives before shell fallbacks.",
            "MCP tools are external protocol adapters, not local ToolExecutionGateway tools.",
            "Skills are loaded workflow knowledge or artifact capabilities, not local tools.",
            "Only the capability decision and evidence record format is shared across Tool, MCP, and Skill.",
        ],
    }
