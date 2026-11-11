"""Auditable changes to planner-proposed methods, never to goal requirements."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.task_verification import (
    VERIFICATION_TOOLS, commands_needing_execution, declared_commands, observation_command,
)
from asteria_runtime.utils.time import now_iso


def authority_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _authority_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for child in value.values() for s in _authority_strings(child)]
    if isinstance(value, list):
        return [s for child in value for s in _authority_strings(child)]
    return []


def load_method_authority(root: Path, project_commands: dict) -> dict | None:
    """Full guidance for authority checks only; never added to the model prompt.

    A prompt's 4k excerpt cannot establish that its omitted tail has no mandatory
    checks. Bound this independent read and fail closed on unreadable/oversized input.
    """
    path = root / "AGENTS.md"
    guidance: dict = {}
    try:
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                content = handle.read(262_145)
            if len(content) > 262_144:
                return None
            guidance = {"content": content, "truncated": False}
    except (OSError, UnicodeError):
        return None
    return {"root_guidance": guidance, "project_commands": project_commands}


def method_provenance(commands: list[str], goal: dict, runtime_context: dict) -> dict | None:
    runtime_context = runtime_context.get("verification_authority", runtime_context)
    if not isinstance(runtime_context, dict):
        return None
    # Absence of loaded context is not evidence that project guidance was absent.
    if "root_guidance" not in runtime_context or not isinstance(runtime_context.get("project_commands"), dict):
        return None
    guidance = runtime_context["root_guidance"]
    if not isinstance(guidance, dict) or guidance.get("truncated"):
        return None
    content = guidance.get("content") if guidance else None
    if guidance and not isinstance(content, str):
        return None
    project_commands = runtime_context["project_commands"]
    authority = [*_authority_strings(goal), *_authority_strings(project_commands), content or ""]
    configured = [*_authority_strings(goal.get("verification_strategy", [])),
                  *_authority_strings(project_commands)]
    # Literal occurrence is deliberately conservative: no shell parsing, command-name
    # heuristics or model-declared 'optional' flags can override higher-level text.
    return {
        "goal_sha256": authority_digest(goal),
        "guidance_sha256": authority_digest(content),
        "project_commands_sha256": authority_digest(project_commands),
        "revisable_commands": [c for c in commands
                               if not any(c in text for text in authority)
                               and not any(text.strip() and text.strip() in c for text in configured)],
    }


def revise_method(
    task: dict, goal: dict, guidance: str | None, project_commands: dict, records: list[dict], *,
    original_command: str, replacement_command: str, reason: str, coverage: str,
) -> dict:
    policy = task.get("verification_policy") or {}
    source = policy.get("method_provenance") or {}
    commands = declared_commands(task)
    original = original_command.strip()
    replacement = replacement_command.strip()
    if (not original or not replacement or original == replacement or replacement in commands
            or original not in commands or original not in source.get("revisable_commands", [])):
        raise PermissionError("Only a provenance-backed planner method can be replaced")
    if (source.get("goal_sha256") != authority_digest(goal)
            or source.get("guidance_sha256") != authority_digest(guidance)
            or source.get("project_commands_sha256") != authority_digest(project_commands)):
        raise PermissionError("Goal or project guidance changed; method authority must be replanned")
    if not reason.strip() or not coverage.strip():
        raise ValueError("A method revision requires a reason and unchanged coverage explanation")
    if task.get("status") != "in_progress":
        raise PermissionError("Only the active in-progress task can revise its method")
    if commands != policy.get("commands"):
        raise PermissionError("Inconsistent task verification commands")

    own = [r for r in records if r.get("task_id") == task["task_id"]]
    observations = [ToolObservation(**r["observation"]) for r in own]
    latest = {observation_command(o): (i, o) for i, o in enumerate(observations)
              if o.tool_name in VERIFICATION_TOOLS}
    failed = latest.get(original)
    passed = latest.get(replacement)
    if (failed is None or passed is None or passed[0] <= failed[0]
            or failed[1].ok or failed[1].status != "failure"
            or type(failed[1].data.get("returncode")) is not int
            or failed[1].data["returncode"] == 0
            or not passed[1].ok or passed[1].status != "success"
            or type(passed[1].data.get("returncode")) is not int
            or passed[1].data["returncode"] != 0):
        raise PermissionError("Need an executed failure followed by an executed zero-exit replacement")
    effects = passed[1].data
    if (effects.get("workspace_scan") != "stat_only"
            or effects.get("workspace_changes") != {"created": [], "modified": [], "deleted": []}):
        raise PermissionError("Replacement evidence must have observed no workspace changes")

    revised = deepcopy(task)
    revised["validation_commands"] = [replacement if c == original else c for c in commands]
    updated_policy = revised["verification_policy"]
    updated_policy["commands"] = list(revised["validation_commands"])
    if replacement in commands_needing_execution(revised, observations):
        raise PermissionError("Replacement evidence is stale after a possible write")
    candidates = [
        replacement if c == original else c for c in source["revisable_commands"]
    ]
    # Adopting a configured/user check never makes that check revisable in a later turn.
    updated_policy["method_provenance"] = method_provenance(candidates, goal, {
        "root_guidance": {} if guidance is None else {"content": guidance, "truncated": False},
        "project_commands": project_commands,
    })
    updated_policy.setdefault("method_revisions", []).append({
        "original_command": original, "replacement_command": replacement,
        "reason": reason.strip(), "coverage": coverage.strip(),
        "failed_observation_id": own[failed[0]]["observation_id"],
        "passed_observation_id": own[passed[0]]["observation_id"],
        "created_at": now_iso(),
    })
    revised["updated_at"] = now_iso()
    return revised
