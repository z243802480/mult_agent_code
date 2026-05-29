from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.runtime_profile import SCHEMA_VERSION
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def build_subagent_child_plan(
    *,
    decision: dict[str, Any],
    execution_result: dict[str, Any],
    task: dict[str, Any] | None = None,
    sequence: int = 1,
) -> dict[str, Any]:
    next_action = decision.get("next_action")
    next_action = next_action if isinstance(next_action, dict) else {}
    expected = next_action.get("expected_observation")
    expected = expected if isinstance(expected, dict) else {}
    task = task if isinstance(task, dict) else {}
    target_task_id = str(next_action.get("target_task_id") or task.get("task_id") or "")
    worker_id = str(execution_result.get("worker_invocation_id") or "")
    strategy = _strategy(task, expected)
    mode = str(strategy.get("mode") or "serial_worker")
    max_child_workers = _positive_int(strategy.get("max_child_workers"), default=1)
    coordination_policy = _dict(strategy.get("coordination_policy"))
    scheduling_strategy = _scheduling_strategy(mode, coordination_policy)
    read_scope = _string_list(expected.get("read_scope") or task.get("read_scope"))
    write_scope = _string_list(
        expected.get("allowed_writes")
        or expected.get("write_scope")
        or task.get("write_scope")
        or task.get("expected_changed_files")
    )
    allowed_tools = _string_list(expected.get("allowed_tools") or task.get("allowed_tools"))
    acceptance = _string_list(
        expected.get("acceptance")
        or task.get("acceptance")
        or [expected.get("success_signal") or "subagent result is recorded"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "subagent_child_plan_id": f"subagent-child-plan-{max(1, sequence):04d}",
        "run_id": str(decision.get("run_id") or execution_result.get("run_id") or ""),
        "parent_task_id": str(decision.get("task_id") or task.get("task_id") or ""),
        "target_task_id": target_task_id,
        "parent_decision_id": str(decision.get("decision_id") or ""),
        "parent_execution_id": str(execution_result.get("execution_id") or ""),
        "worker_invocation_id": worker_id,
        "worker_result_id": str(execution_result.get("worker_result_id") or ""),
        "runtime_profile_id": str(execution_result.get("runtime_profile_id") or ""),
        "planner_id": "runtime_subagent_decomposer",
        "decomposition_strategy": _decomposition_strategy(mode, max_child_workers),
        "scheduling_strategy": scheduling_strategy,
        "max_child_workers": max_child_workers,
        "coordination_policy": coordination_policy,
        "status": "planned",
        "parallel_safety": str(
            expected.get("parallel_safety") or task.get("parallel_safety") or "serial"
        ),
        "child_tasks": _child_tasks(
            target_task_id=target_task_id,
            worker_id=worker_id,
            sequence=sequence,
            task=task,
            expected=expected,
            next_action=next_action,
            mode=mode,
            max_child_workers=max_child_workers,
            read_scope=read_scope,
            write_scope=write_scope,
            allowed_tools=allowed_tools,
            acceptance=acceptance,
        ),
        "evidence_refs": _string_list(next_action.get("evidence_refs")),
        "created_at": now_iso(),
    }


def persist_subagent_child_plan(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    decision: dict[str, Any],
    execution_result: dict[str, Any],
    task: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "subagent_child_plans.jsonl"
    store = JsonlStore(validator)
    existing = store.read_all(path, "subagent_child_plan") if path.exists() else []
    plan = build_subagent_child_plan(
        decision=decision,
        execution_result=execution_result,
        task=task,
        sequence=len(existing) + 1,
    )
    store.append(path, plan, "subagent_child_plan")
    return plan


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if str(item)]
    text = str(value)
    return [text] if text else []


def _strategy(task: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    raw = expected.get("multi_agent_strategy") or task.get("multi_agent_strategy")
    return raw if isinstance(raw, dict) else {}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _decomposition_strategy(mode: str, max_child_workers: int) -> str:
    if mode == "readonly_fanout" and max_child_workers > 1:
        return "readonly_fanout_child_tasks"
    if mode == "disjoint_write_workers" and max_child_workers > 1:
        return "disjoint_write_child_tasks"
    if mode == "plan_then_serial":
        return "serial_planned_child_task"
    return "single_child_task"


def _scheduling_strategy(mode: str, coordination_policy: dict[str, Any]) -> str:
    if mode == "readonly_fanout":
        return "parallel_readonly_safe"
    if mode == "disjoint_write_workers":
        return (
            "parallel_disjoint_writes_after_merge_gate"
            if coordination_policy.get("requires_disjoint_write_scope", True)
            else "serial_write_fallback"
        )
    if mode == "plan_then_serial":
        return "serial_plan_then_execute"
    return "serial_single_worker"


def _child_tasks(
    *,
    target_task_id: str,
    worker_id: str,
    sequence: int,
    task: dict[str, Any],
    expected: dict[str, Any],
    next_action: dict[str, Any],
    mode: str,
    max_child_workers: int,
    read_scope: list[str],
    write_scope: list[str],
    allowed_tools: list[str],
    acceptance: list[str],
) -> list[dict[str, Any]]:
    if mode == "disjoint_write_workers" and len(write_scope) > 1:
        outputs = _string_list(expected.get("expected_output") or task.get("expected_artifacts"))
        return [
            _child_task(
                target_task_id=target_task_id,
                worker_id=worker_id,
                sequence=sequence,
                index=index,
                task=task,
                expected=expected,
                next_action=next_action,
                title=f"Update {path}",
                objective=f"Complete delegated write target {path}.",
                acceptance=_item_or_all(acceptance, index),
                read_scope=read_scope,
                write_scope=[path],
                allowed_tools=allowed_tools,
                expected_output=_matching_outputs(outputs, path),
                parallel_safety="disjoint_writes",
                worker_role="implementation_child",
                write_allowed=True,
            )
            for index, path in enumerate(write_scope[:max_child_workers], start=1)
        ]
    if mode == "readonly_fanout" and max_child_workers > 1:
        fallback_label = str(
            expected.get("summary") or next_action.get("reason") or "readonly delegated task"
        )
        slices = acceptance or read_scope or [fallback_label]
        return [
            _child_task(
                target_task_id=target_task_id,
                worker_id=worker_id,
                sequence=sequence,
                index=index,
                task=task,
                expected=expected,
                next_action=next_action,
                title=f"Inspect {label}",
                objective=f"Collect readonly evidence for {label}.",
                acceptance=[str(label)],
                read_scope=read_scope,
                write_scope=[],
                allowed_tools=_readonly_tools(allowed_tools),
                expected_output=[str(label)],
                parallel_safety="readonly",
                worker_role="research_child",
                write_allowed=False,
            )
            for index, label in enumerate(slices[:max_child_workers], start=1)
            if str(label)
        ]
    return [
        _child_task(
            target_task_id=target_task_id,
            worker_id=worker_id,
            sequence=sequence,
            index=1,
            task=task,
            expected=expected,
            next_action=next_action,
            title=str(
                expected.get("title")
                or task.get("title")
                or task.get("description")
                or next_action.get("reason")
                or target_task_id
            ),
            objective=str(
                expected.get("summary")
                or next_action.get("reason")
                or task.get("description")
                or "Complete the delegated subagent task."
            ),
            acceptance=acceptance,
            read_scope=read_scope,
            write_scope=write_scope,
            allowed_tools=allowed_tools,
            expected_output=_string_list(
                expected.get("expected_output")
                or task.get("expected_artifacts")
                or [expected.get("success_signal") or "subagent observation"]
            ),
            parallel_safety=str(
                expected.get("parallel_safety") or task.get("parallel_safety") or "serial"
            ),
            worker_role="serial_child",
            write_allowed=bool(write_scope),
        )
    ]


def _child_task(
    *,
    target_task_id: str,
    worker_id: str,
    sequence: int,
    index: int,
    task: dict[str, Any],
    expected: dict[str, Any],
    next_action: dict[str, Any],
    title: str,
    objective: str,
    acceptance: list[str],
    read_scope: list[str],
    write_scope: list[str],
    allowed_tools: list[str],
    expected_output: list[str],
    parallel_safety: str,
    worker_role: str,
    write_allowed: bool,
) -> dict[str, Any]:
    child_task_suffix = worker_id or f"{max(1, sequence):04d}"
    return {
        "child_task_id": f"{target_task_id}-child-{child_task_suffix}-{index:02d}",
        "task_id": target_task_id,
        "title": title,
        "objective": objective,
        "acceptance": acceptance,
        "read_scope": read_scope,
        "write_scope": write_scope,
        "allowed_tools": allowed_tools,
        "depends_on": _string_list(task.get("depends_on")),
        "risk": str(next_action.get("risk") or task.get("risk") or "medium"),
        "parallel_safety": parallel_safety,
        "worker_role": worker_role,
        "write_allowed": write_allowed,
        "expected_output": expected_output,
        "verification_expectation": {
            "success_signal": expected.get("success_signal"),
            "validation_commands": _string_list(task.get("validation_commands")),
        },
    }


def _item_or_all(values: list[str], index: int) -> list[str]:
    if not values:
        return []
    if index - 1 < len(values):
        return [values[index - 1]]
    return values


def _matching_outputs(outputs: list[str], path: str) -> list[str]:
    matching = [item for item in outputs if item == path or item.startswith(path)]
    return matching or [path]


def _readonly_tools(allowed_tools: list[str]) -> list[str]:
    readonly = {"list_files", "read_file", "search_text", "diff_workspace", "run_command", "run_tests"}
    filtered = [tool for tool in allowed_tools if tool in readonly]
    return filtered or ["list_files", "read_file", "search_text", "diff_workspace"]
