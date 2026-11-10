"""Declared task checks are completion criteria; other probes remain observations."""

from dataclasses import replace
from typing import Any

from asteria_runtime.core.agent_harness import ToolObservation, observation_from_exception


VERIFICATION_TOOLS = frozenset({"run_command", "run_tests", "run_pytest"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch", "restore_backup", "shell"})


def declared_commands(task: dict) -> list[str]:
    policy = task.get("verification_policy") or {}
    if policy.get("command_source") != "planner_task":
        return []
    return [str(c).strip() for c in task.get("validation_commands", []) if str(c).strip()]


def observation_command(observation: Any) -> str:
    data = getattr(observation, "data", {}) or {}
    return str(data.get("requested_command") or data.get("command") or "").strip()


def commands_needing_execution(task: dict, observations: list[ToolObservation]) -> list[str]:
    commands = declared_commands(task)
    latest: dict[str, int] = {}
    last_mutation = -1
    for index, obs in enumerate(observations):
        name = obs.tool_name
        command = observation_command(obs)
        if name in VERIFICATION_TOOLS and command in commands:
            latest[command] = index
        elif name in VERIFICATION_TOOLS | _WRITE_TOOLS or obs.data.get("changed_files"):
            # An arbitrary command can mutate files, even if it reports failure.
            last_mutation = index
    return [c for c in commands if latest.get(c, -1) < last_mutation or c not in latest]


def declared_observations(task: dict, observations: list[ToolObservation]) -> list[ToolObservation]:
    latest = {
        observation_command(obs): obs
        for obs in observations if obs.tool_name in VERIFICATION_TOOLS
    }
    result = []
    for command in declared_commands(task):
        if command in latest:
            result.append(latest[command])
        else:
            missing = observation_from_exception(
                tool_name="run_tests", exc=RuntimeError("Required task validation was not executed")
            )
            result.append(replace(missing, data={**missing.data, "command": command}))
    return result
