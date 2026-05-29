from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import NEXT_ACTIONS
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RuntimeReadinessCheck:
    name: str
    status: str
    summary: str
    recommended_action: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": self.evidence_refs,
        }
        if self.recommended_action:
            data["recommended_action"] = self.recommended_action
        return data


def runtime_readiness_gate(
    *,
    root: Path,
    validator: SchemaValidator,
    model_call_contract: dict[str, Any],
    context_pressure_summary: dict[str, Any],
    latest_observation_plan: dict[str, Any],
    route_guidance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine route/deadline/context/capability/decision evidence into one gate."""

    run_dirs = _run_dirs(root)
    checks = [
        _model_contract_check(model_call_contract),
        _route_guidance_check(route_guidance or {}),
        _context_pressure_check(context_pressure_summary),
        _subagent_context_isolation_check(run_dirs, validator),
        _observation_decision_check(run_dirs, validator, latest_observation_plan),
        _agent_loop_execution_check(run_dirs, validator),
        _capability_selection_check(run_dirs, validator),
    ]
    blocking = [check for check in checks if check.status == "blocked"]
    review = [check for check in checks if check.status == "review"]
    if blocking:
        status = "blocked"
    elif review:
        status = "review"
    else:
        status = "ready"
    next_actions = [
        str(check.recommended_action)
        for check in [*blocking, *review]
        if check.recommended_action
    ]
    return {
        "schema_version": "0.1.0",
        "status": status,
        "blocked": len(blocking),
        "review": len(review),
        "ready": len([check for check in checks if check.status == "ready"]),
        "checks": [check.to_dict() for check in checks],
        "next_actions": next_actions,
    }


def _model_contract_check(contract: dict[str, Any]) -> RuntimeReadinessCheck:
    status = str(contract.get("status") or "unknown")
    if status == "blocked":
        return RuntimeReadinessCheck(
            name="model_call_contract",
            status="blocked",
            summary="Recent real-provider model calls are missing role contract, deadline, or streaming telemetry.",
            recommended_action="Run `asteria model-check --json`, then rerun the affected real-provider task.",
            evidence_refs=[
                str(item.get("path"))
                for item in contract.get("violations", [])
                if isinstance(item, dict) and item.get("path")
            ][:5],
        )
    if status == "healthy":
        return RuntimeReadinessCheck(
            name="model_call_contract",
            status="ready",
            summary="Recent real-provider model calls include role/deadline/streaming telemetry.",
        )
    return RuntimeReadinessCheck(
        name="model_call_contract",
        status="review",
        summary="No fresh real-provider model call contract evidence was found.",
        recommended_action="Run `asteria model-check --json` before widening validation.",
    )


def _route_guidance_check(guidance: dict[str, Any]) -> RuntimeReadinessCheck:
    status = str(guidance.get("status") or "unknown")
    if status == "blocked":
        actions = list(guidance.get("recommended_actions") or [])
        return RuntimeReadinessCheck(
            name="route_guidance",
            status="blocked",
            summary="Provider route guidance is blocked by recent capability evidence.",
            recommended_action=str(actions[0])
            if actions
            else "Run `asteria model-check --tier strong --json` and refresh route evidence.",
            evidence_refs=[
                str(item.get("recommended_action"))
                for item in guidance.get("blocking", [])
                if isinstance(item, dict) and item.get("recommended_action")
            ][:5],
        )
    if status == "review":
        actions = list(guidance.get("recommended_actions") or [])
        return RuntimeReadinessCheck(
            name="route_guidance",
            status="review",
            summary="Provider route guidance needs review before widening validation.",
            recommended_action=str(actions[0])
            if actions
            else "Run `asteria capability-report` after fresh route evidence.",
        )
    if status == "healthy":
        return RuntimeReadinessCheck(
            name="route_guidance",
            status="ready",
            summary="Provider route guidance is healthy.",
        )
    return RuntimeReadinessCheck(
        name="route_guidance",
        status="review",
        summary="No provider route guidance evidence was found.",
        recommended_action="Run `asteria capability-report` after collecting model route evidence.",
    )


def _context_pressure_check(summary: dict[str, Any]) -> RuntimeReadinessCheck:
    ratio = float(summary.get("max_context_window_ratio") or 0.0)
    if ratio >= 0.9:
        return RuntimeReadinessCheck(
            name="context_pressure",
            status="blocked",
            summary=f"Context pressure is at hard-stop level ({ratio:.2f}).",
            recommended_action="Run `asteria compact --root .` before continuing.",
        )
    if ratio >= 0.75:
        return RuntimeReadinessCheck(
            name="context_pressure",
            status="review",
            summary=f"Context pressure is near compaction threshold ({ratio:.2f}).",
            recommended_action="Run `asteria compact --root .` or narrow the next task context.",
        )
    return RuntimeReadinessCheck(
        name="context_pressure",
        status="ready",
        summary="Context pressure is within the configured window.",
    )


def _subagent_context_isolation_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    worker = _latest_subagent_worker(run_dirs, validator)
    if not worker:
        return RuntimeReadinessCheck(
            name="subagent_context_isolation",
            status="ready",
            summary="No subagent child worker context isolation evidence is required yet.",
        )
    worker_id = str(worker.get("worker_invocation_id") or "")
    snapshot = _latest_context_budget_snapshot_for_worker(run_dirs, validator, worker_id)
    if not snapshot:
        return RuntimeReadinessCheck(
            name="subagent_context_isolation",
            status="review",
            summary="Latest subagent worker has no ContextBudgetMeter v2 child context snapshot.",
            recommended_action=(
                "Rerun the subagent path so Runtime records context_budget_snapshots.jsonl "
                "with child token attribution and compact boundary evidence."
            ),
            evidence_refs=[worker_id],
        )
    pressure = str(snapshot.get("pressure_status") or "")
    ratio = float(snapshot.get("context_window_ratio") or 0.0)
    compact_boundary = snapshot.get("compact_boundary")
    compact_boundary = compact_boundary if isinstance(compact_boundary, dict) else {}
    boundary_status = str(compact_boundary.get("status") or "")
    evidence_refs = [
        worker_id,
        str(snapshot.get("snapshot_id") or ""),
        *[str(item) for item in snapshot.get("evidence_refs") or [] if item],
    ][:8]
    if pressure in {"hard_stop", "exceeded"} or boundary_status == "required":
        return RuntimeReadinessCheck(
            name="subagent_context_isolation",
            status="blocked",
            summary=f"Subagent child context is at compact hard-stop boundary ({ratio:.2f}).",
            recommended_action="Run `asteria compact --root .` before continuing the child worker loop.",
            evidence_refs=evidence_refs,
        )
    if pressure == "near_limit" or boundary_status == "recommended":
        return RuntimeReadinessCheck(
            name="subagent_context_isolation",
            status="review",
            summary=f"Subagent child context is near compaction boundary ({ratio:.2f}).",
            recommended_action="Compact or narrow the child read/evidence scope before widening parallel work.",
            evidence_refs=evidence_refs,
        )
    duplicate_tokens = int(snapshot.get("duplicate_estimated_tokens") or 0)
    estimated = max(1, int(snapshot.get("estimated_tokens") or 1))
    if boundary_status == "dedupe_recommended" or duplicate_tokens / estimated >= 0.2:
        return RuntimeReadinessCheck(
            name="subagent_context_isolation",
            status="review",
            summary=(
                "Subagent child context contains repeated mounted content "
                f"({duplicate_tokens} duplicate estimated tokens)."
            ),
            recommended_action="Dedupe repeated child context before enabling broader parallel dispatch.",
            evidence_refs=evidence_refs,
        )
    return RuntimeReadinessCheck(
        name="subagent_context_isolation",
        status="ready",
        summary="Subagent child context snapshot includes token attribution and compact boundary evidence.",
        evidence_refs=evidence_refs,
    )


def _observation_decision_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
    latest_plan: dict[str, Any],
) -> RuntimeReadinessCheck:
    failed = int(latest_plan.get("failed_observation_count") or 0)
    latest_decision = _latest_decision(
        run_dirs,
        validator,
        run_id=str(latest_plan.get("run_id") or "") or None,
        task_id=str(latest_plan.get("task_id") or "") or None,
    )
    if failed <= 0:
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="ready",
            summary="No unresolved failed observation plan was found.",
        )
    if not latest_decision:
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="blocked",
            summary="Failed observations exist but no AgentLoopDecision evidence was recorded.",
            recommended_action="Run `asteria debug` or `asteria replan` so the model picks repair/replan/ask/stop explicitly.",
            evidence_refs=list(latest_plan.get("evidence_refs") or [])[:5],
        )
    action = str(((latest_decision.get("next_action") or {}).get("action")) or "")
    if action not in NEXT_ACTIONS:
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="blocked",
            summary=f"Latest AgentLoopDecision used unsupported action `{action}`.",
            recommended_action="Regenerate the agent decision with tool/subagent/repair/replan/ask/stop.",
        )
    if action == "tool" and failed > 0:
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="review",
            summary="Failed observations exist and the latest decision chose another tool action.",
            recommended_action="Prefer `asteria debug`, `asteria replan`, or a DecisionPoint before another tool call.",
        )
    if action in {"repair", "replan", "ask", "stop"}:
        command = {
            "repair": "asteria debug",
            "replan": "asteria replan",
            "ask": "asteria decide --list",
            "stop": "asteria status --debug",
        }[action]
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="review",
            summary=f"Failed observations are covered by explicit `{action}` AgentLoopDecision evidence.",
            recommended_action=f"Run `{command}` to continue the recorded recovery decision.",
            evidence_refs=[
                str(latest_decision.get("decision_id") or ""),
                *list(latest_plan.get("evidence_refs") or [])[:4],
            ],
        )
    return RuntimeReadinessCheck(
        name="observation_next_action",
        status="ready",
        summary=f"Failed observations are covered by explicit `{action}` AgentLoopDecision evidence.",
    )


def _capability_selection_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    selected = _selected_capabilities(run_dirs)
    if not selected:
        return RuntimeReadinessCheck(
            name="capability_selection",
            status="review",
            summary="No task capability catalog evidence was found for recent runs.",
            recommended_action="Run a small validation task so capability catalog and actual selections can be compared.",
        )
    actual = _actual_capability_decisions(run_dirs, validator)
    if not actual:
        return RuntimeReadinessCheck(
            name="capability_selection",
            status="review",
            summary="Capability catalog exists, but no capability decision evidence was found.",
            recommended_action="Run a task through the Tool/Skill/MCP gateway to record capability decisions.",
        )
    unexpected = sorted(item for item in actual if item not in selected)
    if unexpected:
        return RuntimeReadinessCheck(
            name="capability_selection",
            status="review",
            summary="Actual capability selections are not fully aligned with task capability catalogs.",
            recommended_action="Inspect `agent_loop_dispatch.json` and `capability_decisions.jsonl` before scaling validation.",
            evidence_refs=unexpected[:5],
        )
    return RuntimeReadinessCheck(
        name="capability_selection",
        status="ready",
        summary="Actual capability selections align with selected task capability catalogs.",
    )


def _agent_loop_execution_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    latest_decision = _latest_decision(run_dirs, validator)
    if not latest_decision:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="ready",
            summary="No AgentLoopDecision evidence requires Runtime dispatch yet.",
        )
    decision_id = str(latest_decision.get("decision_id") or "")
    execution = _latest_execution_for_decision(run_dirs, validator, decision_id)
    if not execution:
        action = str(((latest_decision.get("next_action") or {}).get("action")) or "unknown")
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary=(
                "Latest AgentLoopDecision has no matching Runtime execution result; "
                f"action `{action}` was not dispatched."
            ),
            recommended_action=(
                "Rerun `asteria execute`, `asteria debug`, or the recovery command so Runtime "
                "records `agent_loop_execution_results.jsonl`."
            ),
            evidence_refs=[decision_id],
        )
    action = str(execution.get("action") or "")
    status = str(execution.get("status") or "")
    target = str(execution.get("target") or "")
    if not action or not status or not target:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary="Latest Runtime execution result is missing action, status, or target.",
            recommended_action="Regenerate the agent loop execution result before widening validation.",
            evidence_refs=[decision_id],
        )
    if action != str(((latest_decision.get("next_action") or {}).get("action")) or ""):
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary="Latest Runtime execution result does not match the AgentLoopDecision action.",
            recommended_action="Regenerate the agent loop decision/execution pair.",
            evidence_refs=[decision_id, str(execution.get("execution_id") or "")],
        )
    if action == "subagent":
        worker_check = _subagent_worker_dispatch_check(run_dirs, validator, execution)
        if worker_check is not None:
            return worker_check
    observation_check = _execution_observation_check(
        run_dirs,
        validator,
        latest_decision,
        execution,
    )
    if observation_check is not None:
        return observation_check
    return RuntimeReadinessCheck(
        name="agent_loop_execution",
        status="ready",
        summary=(
            f"Latest AgentLoopDecision was dispatched to `{target}` with status `{status}`."
        ),
        evidence_refs=[decision_id, str(execution.get("execution_id") or "")],
    )


def _selected_capabilities(run_dirs: list[Path]) -> set[str]:
    selected: set[str] = set()
    for run_dir in run_dirs[-20:]:
        path = run_dir / "agent_loop_dispatch.json"
        if not path.exists():
            continue
        try:
            dispatch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for task in dispatch.get("task_dispatch", []) or []:
            catalog = task.get("capability_catalog") if isinstance(task, dict) else None
            if not isinstance(catalog, dict):
                continue
            for entry in catalog.get("entries", []) or []:
                if not isinstance(entry, dict) or entry.get("selection_state") != "selected":
                    continue
                selected.add(f"{entry.get('capability_type')}:{entry.get('name')}")
    return selected


def _actual_capability_decisions(run_dirs: list[Path], validator: SchemaValidator) -> set[str]:
    actual: set[str] = set()
    store = JsonlStore(validator)
    for run_dir in run_dirs[-20:]:
        path = run_dir / "capability_decisions.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, None):
            decision = item.get("decision") if isinstance(item, dict) else None
            if isinstance(decision, dict) and decision.get("decision") == "deny":
                continue
            capability_type = str(item.get("capability_type") or "tool")
            capability = str(item.get("capability") or item.get("name") or "")
            if capability:
                actual.add(f"{capability_type}:{capability}")
    return actual


def _latest_decision(
    run_dirs: list[Path],
    validator: SchemaValidator,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    fallback: dict[str, Any] | None = None
    fallback_created = ""
    for run_dir in run_dirs:
        path = run_dir / "agent_loop_decisions.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "agent_loop_decision"):
            created = str(item.get("created_at") or "")
            if fallback is None or created >= fallback_created:
                fallback = item
                fallback_created = created
            if run_id and str(item.get("run_id") or "") != run_id:
                continue
            if task_id and str(item.get("task_id") or "") != task_id:
                continue
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    if latest is not None:
        return latest
    if run_id or task_id:
        return fallback
    return latest


def _subagent_worker_dispatch_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
    execution: dict[str, Any],
) -> RuntimeReadinessCheck | None:
    worker_id = str(execution.get("worker_invocation_id") or "")
    worker_result_id = str(execution.get("worker_result_id") or "")
    runtime_profile_id = str(execution.get("runtime_profile_id") or "")
    if not worker_id or not worker_result_id or not runtime_profile_id:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary="Subagent execution result is missing worker dispatch evidence.",
            recommended_action="Rerun the subagent dispatch so Runtime records workers.jsonl and worker_results.jsonl.",
            evidence_refs=[str(execution.get("execution_id") or "")],
        )
    worker = _worker_by_id(run_dirs, validator, worker_id)
    result = _worker_result_by_id(run_dirs, validator, worker_result_id)
    if not worker or not result:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary="Subagent execution result references worker evidence that was not found.",
            recommended_action="Inspect workers.jsonl, worker_results.jsonl, and rerun the subagent dispatch if needed.",
            evidence_refs=[worker_id, worker_result_id],
        )
    if str(worker.get("runtime_profile_id") or "") != runtime_profile_id:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="review",
            summary="Subagent worker runtime profile differs from the execution result.",
            recommended_action="Inspect the subagent worker profile before widening validation.",
            evidence_refs=[worker_id, worker_result_id],
        )
    result_status = str(result.get("status") or "")
    if result_status in {"failed", "denied", "timeout"}:
        observation = _latest_observation_for_execution(
            run_dirs,
            validator,
            str(execution.get("execution_id") or ""),
        )
        recovery = _latest_decision_after_observation(run_dirs, validator, observation) if observation else None
        if not recovery:
            return RuntimeReadinessCheck(
                name="agent_loop_execution",
                status="blocked",
                summary=(
                    f"Subagent worker recorded `{result_status}` but no parent "
                    "repair/replan/ask/stop decision corrected it."
                ),
                recommended_action=(
                    "Run `asteria debug`, `asteria replan`, or `asteria decide --list` "
                    "so the parent loop consumes the subagent failure."
                ),
                evidence_refs=[worker_id, worker_result_id],
            )
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="review",
            summary=f"Subagent worker `{result_status}` is covered by parent recovery decision.",
            recommended_action="Continue the recorded parent loop recovery action.",
            evidence_refs=[worker_id, worker_result_id, str(recovery.get("decision_id") or "")],
        )
    return None


def _execution_observation_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
    decision: dict[str, Any],
    execution: dict[str, Any],
) -> RuntimeReadinessCheck | None:
    execution_id = str(execution.get("execution_id") or "")
    observation = _latest_observation_for_execution(run_dirs, validator, execution_id)
    if not observation:
        return RuntimeReadinessCheck(
            name="agent_loop_execution",
            status="blocked",
            summary=(
                "Latest Runtime execution result has no matching AgentLoopObservation; "
                "the loop cannot feed an observation back to the model."
            ),
            recommended_action=(
                "Rerun the action through AgentLoopRunner or regenerate "
                "`agent_loop_observations.jsonl` from execution evidence."
            ),
            evidence_refs=[str(decision.get("decision_id") or ""), execution_id],
        )
    status = str(observation.get("status") or "")
    if status in {"failed", "blocked"}:
        recovery = _latest_decision_after_observation(run_dirs, validator, observation)
        if not recovery:
            return RuntimeReadinessCheck(
                name="agent_loop_execution",
                status="blocked",
                summary=(
                    "Failed AgentLoopObservation was recorded but no follow-up "
                    "AgentLoopDecision entered repair/replan/ask/stop."
                ),
                recommended_action=(
                    "Run `asteria debug`, `asteria replan`, `asteria decide --list`, "
                    "or stop explicitly so the model chooses a recovery action."
                ),
                evidence_refs=[execution_id, str(observation.get("observation_id") or "")],
            )
        recovery_action = str(((recovery.get("next_action") or {}).get("action")) or "")
        if recovery_action not in {"repair", "replan", "ask", "stop"}:
            return RuntimeReadinessCheck(
                name="agent_loop_execution",
                status="blocked",
                summary=(
                    "Failed AgentLoopObservation has a follow-up decision, but it did "
                    f"not choose recovery action; got `{recovery_action}`."
                ),
                recommended_action="Regenerate the follow-up decision as repair/replan/ask/stop.",
                evidence_refs=[
                    execution_id,
                    str(observation.get("observation_id") or ""),
                    str(recovery.get("decision_id") or ""),
                ],
            )
    return None


def _latest_execution_for_decision(
    run_dirs: list[Path],
    validator: SchemaValidator,
    decision_id: str,
) -> dict[str, Any] | None:
    if not decision_id:
        return None
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "agent_loop_execution_results.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "agent_loop_execution_result"):
            if str(item.get("decision_id") or "") != decision_id:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _latest_observation_for_execution(
    run_dirs: list[Path],
    validator: SchemaValidator,
    execution_id: str,
) -> dict[str, Any] | None:
    if not execution_id:
        return None
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "agent_loop_observations.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "agent_loop_observation"):
            if str(item.get("source_execution_id") or "") != execution_id:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _latest_decision_after_observation(
    run_dirs: list[Path],
    validator: SchemaValidator,
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    source_decision_id = str(observation.get("source_decision_id") or "")
    created_at = str(observation.get("created_at") or "")
    run_id = str(observation.get("run_id") or "")
    task_id = str(observation.get("task_id") or "")
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "agent_loop_decisions.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "agent_loop_decision"):
            if str(item.get("decision_id") or "") == source_decision_id:
                continue
            if run_id and str(item.get("run_id") or "") != run_id:
                continue
            if task_id and str(item.get("task_id") or "") != task_id:
                continue
            item_created = str(item.get("created_at") or "")
            if item_created < created_at:
                continue
            if latest is None or item_created >= latest_created:
                latest = item
                latest_created = item_created
    return latest


def _worker_by_id(
    run_dirs: list[Path],
    validator: SchemaValidator,
    worker_id: str,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    for run_dir in run_dirs:
        path = run_dir / "workers.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "worker_invocation"):
            if str(item.get("worker_invocation_id") or "") == worker_id:
                latest = item
    return latest


def _worker_result_by_id(
    run_dirs: list[Path],
    validator: SchemaValidator,
    worker_result_id: str,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    for run_dir in run_dirs:
        path = run_dir / "worker_results.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "worker_result"):
            if str(item.get("worker_result_id") or "") == worker_result_id:
                latest = item
    return latest


def _latest_subagent_worker(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_started = ""
    for run_dir in run_dirs:
        path = run_dir / "workers.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "worker_invocation"):
            if str(item.get("worker_kind") or "") != "subagent":
                continue
            started = str(item.get("started_at") or "")
            if latest is None or started >= latest_started:
                latest = item
                latest_started = started
    return latest


def _latest_context_budget_snapshot_for_worker(
    run_dirs: list[Path],
    validator: SchemaValidator,
    worker_id: str,
) -> dict[str, Any] | None:
    if not worker_id:
        return None
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "context_budget_snapshots.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "context_budget_snapshot"):
            if str(item.get("scope") or "") != "subagent_child":
                continue
            if str(item.get("parent_worker_invocation_id") or "") != worker_id:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _run_dirs(root: Path) -> list[Path]:
    runs_dir = root / ".asteria" / "runs"
    if not runs_dir.exists():
        return []
    return sorted([path for path in runs_dir.iterdir() if path.is_dir()])
