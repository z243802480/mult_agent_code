"""Declared task checks are completion criteria; other probes remain observations."""

from dataclasses import replace
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_harness import ToolObservation, observation_from_exception
from asteria_runtime.core.task_contract import task_kind, write_scope


VERIFICATION_TOOLS = frozenset({"run_command", "run_tests", "run_pytest"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch", "restore_backup", "shell"})


def declared_commands(task: dict) -> list[str]:
    policy = task.get("verification_policy") or {}
    if policy.get("command_source") != "planner_task":
        return []
    return [str(c).strip() for c in task.get("validation_commands", []) if str(c).strip()]


def _readback_contract(task: dict) -> bool:
    policy = task.get("verification_policy") or {}
    return (policy.get("command_source") == "planner_task"
            and isinstance(policy.get("readback_paths"), list)
            and task_kind(task) in {"diagnostic", "verification"} and not write_scope(task))


def declared_readbacks(task: dict) -> list[str]:
    if not _readback_contract(task):
        return []
    return list(dict.fromkeys(str(p).strip() for p in task["verification_policy"]["readback_paths"]
                              if str(p).strip()))


def has_declared_checks(task: dict) -> bool:
    # An explicitly empty readback contract must fail for missing evidence, not inherit
    # unrelated successful probes. Plans without this field keep their legacy behavior.
    return bool(declared_commands(task)) or _readback_contract(task)


def _path_key(value: str, root: Path | None) -> str:
    path = Path(str(value).replace("\\", "/"))
    if root is not None and path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            pass
    return path.as_posix()


def _readback_keys(obs: ToolObservation, root: Path | None) -> set[str]:
    if obs.tool_name != "read_file":
        return set()
    return {_path_key(str(obs.data[key]), root) for key in ("path", "requested_path")
            if obs.data.get(key)}


def readbacks_needing_execution(
    task: dict, observations: list[ToolObservation], root: Path | None = None,
) -> list[str]:
    latest: dict[str, int] = {}
    last_mutation = -1
    for index, obs in enumerate(observations):
        for key in _readback_keys(obs, root):
            latest[key] = index
        if obs.tool_name in VERIFICATION_TOOLS | _WRITE_TOOLS or obs.data.get("changed_files"):
            last_mutation = index
    return [path for path in declared_readbacks(task)
            if _path_key(path, root) not in latest
            or latest[_path_key(path, root)] < last_mutation]


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


def declared_observations(
    task: dict, observations: list[ToolObservation], root: Path | None = None,
) -> list[ToolObservation]:
    latest = {
        observation_command(obs): obs
        for obs in observations if obs.tool_name in VERIFICATION_TOOLS
    }
    result = []
    stale_commands = set(commands_needing_execution(task, observations))
    for command in declared_commands(task):
        if command in latest and not (latest[command].ok and command in stale_commands):
            result.append(latest[command])
        else:
            missing = observation_from_exception(
                tool_name="run_tests", exc=RuntimeError(
                    "Required task validation is missing or stale after a possible write"
                ),
            )
            result.append(replace(missing, data={**missing.data, "command": command}))
    readbacks = {key: obs for obs in observations for key in _readback_keys(obs, root)}
    stale_paths = set(readbacks_needing_execution(task, observations, root))
    for path in declared_readbacks(task):
        key = _path_key(path, root)
        if key in readbacks and not (readbacks[key].ok and path in stale_paths):
            result.append(readbacks[key])
        else:
            missing = observation_from_exception(
                tool_name="read_file", exc=RuntimeError(
                    "Required task file evidence is missing or stale after a possible write"
                ),
            )
            result.append(replace(missing, data={**missing.data, "path": path}))
    return result
