from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import NEXT_ACTIONS
from asteria_runtime.core.disjoint_write_gate import DisjointWriteGate
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
        _subagent_readonly_fanout_check(run_dirs, validator),
        _subagent_disjoint_write_gate_check(run_dirs, validator),
        _candidate_promotion_safety_check(run_dirs, validator),
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
    duplicate_threshold = max(2000, int(estimated * 0.2))
    if boundary_status == "dedupe_recommended" or duplicate_tokens >= duplicate_threshold:
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


def _subagent_readonly_fanout_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    plan = _latest_readonly_fanout_plan(run_dirs, validator)
    if not plan:
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="ready",
            summary="No readonly fanout child worker evidence is required yet.",
        )
    plan_id = str(plan.get("subagent_child_plan_id") or "")
    parent_worker_id = str(plan.get("worker_invocation_id") or "")
    children = [item for item in plan.get("child_tasks") or [] if isinstance(item, dict)]
    evidence_refs = [plan_id, parent_worker_id]
    boundary_error = _readonly_fanout_boundary_error(plan)
    if boundary_error is not None:
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="blocked",
            summary=f"Readonly fanout plan violates its scheduling boundary: {boundary_error}.",
            recommended_action=(
                "Regenerate the subagent child plan with readonly child tasks before "
                "dispatching fanout workers."
            ),
            evidence_refs=[item for item in evidence_refs if item],
        )
    if not parent_worker_id or not children:
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="blocked",
            summary="Readonly fanout plan is missing parent worker or child task evidence.",
            recommended_action="Rerun the subagent planner so fanout scheduling evidence is complete.",
            evidence_refs=[item for item in evidence_refs if item],
        )

    workers = _workers_for_parent(run_dirs, validator, parent_worker_id)
    child_workers = {
        str(worker.get("task_id") or ""): worker
        for worker in workers
        if str(worker.get("worker_kind") or "") == "subagent_readonly_child"
    }
    results = _worker_results_by_worker(run_dirs, validator)
    runtime_profiles = _runtime_profiles_by_id(run_dirs, validator)
    missing_workers: list[str] = []
    missing_results: list[str] = []
    missing_profiles: list[str] = []
    missing_snapshots: list[str] = []
    missing_validation: list[str] = []
    bad_statuses: list[str] = []
    bad_summaries: list[str] = []
    total_model_calls = 0
    total_tool_calls = 0
    child_evidence_refs: list[str] = []

    for child in children:
        child_task_id = str(child.get("child_task_id") or child.get("task_id") or "")
        worker = child_workers.get(child_task_id)
        if not worker:
            missing_workers.append(child_task_id)
            continue
        worker_id = str(worker.get("worker_invocation_id") or "")
        runtime_profile_id = str(worker.get("runtime_profile_id") or "")
        child_evidence_refs.append(worker_id)
        if str(worker.get("parallel_safety") or "") != "readonly":
            return RuntimeReadinessCheck(
                name="subagent_readonly_fanout",
                status="blocked",
                summary=f"Readonly fanout child worker `{worker_id}` is not marked readonly.",
                recommended_action="Rerun fanout dispatch after fixing child worker parallel_safety.",
                evidence_refs=[plan_id, worker_id],
            )
        result = results.get(worker_id)
        if not result:
            missing_results.append(worker_id)
            continue
        result_id = str(result.get("worker_result_id") or "")
        child_evidence_refs.append(result_id)
        status = str(result.get("status") or "")
        raw_cost = result.get("cost")
        cost: dict[str, Any] = raw_cost if isinstance(raw_cost, dict) else {}
        total_model_calls += int(cost.get("model_calls") or 0)
        total_tool_calls += int(cost.get("tool_calls") or 0)
        if status != "succeeded":
            bad_statuses.append(f"{worker_id}:{status or 'unknown'}")
            bad_summaries.append(str(result.get("summary") or ""))
        if not list(result.get("validation_refs") or []) and status == "succeeded":
            missing_validation.append(worker_id)
        if runtime_profile_id not in runtime_profiles:
            missing_profiles.append(worker_id)
        snapshot = _latest_context_budget_snapshot_for_runtime_profile(
            run_dirs,
            validator,
            runtime_profile_id,
            child_task_id,
        )
        if not snapshot:
            missing_snapshots.append(worker_id)
        else:
            snapshot_id = str(snapshot.get("snapshot_id") or "")
            if snapshot_id:
                child_evidence_refs.append(snapshot_id)
            pressure = str(snapshot.get("pressure_status") or "")
            boundary = snapshot.get("compact_boundary")
            boundary = boundary if isinstance(boundary, dict) else {}
            if pressure in {"hard_stop", "exceeded"} or boundary.get("status") == "required":
                return RuntimeReadinessCheck(
                    name="subagent_readonly_fanout",
                    status="blocked",
                    summary=f"Readonly fanout child `{worker_id}` is at compact hard-stop boundary.",
                    recommended_action="Run `asteria compact --root .` before rerunning fanout dispatch.",
                    evidence_refs=[plan_id, worker_id, snapshot_id],
                )
            if pressure == "near_limit" or boundary.get("status") == "recommended":
                return RuntimeReadinessCheck(
                    name="subagent_readonly_fanout",
                    status="review",
                    summary=f"Readonly fanout child `{worker_id}` is near compaction boundary.",
                    recommended_action="Compact or narrow fanout read scope before widening validation.",
                    evidence_refs=[plan_id, worker_id, snapshot_id],
                )

    if missing_workers or missing_results or missing_profiles or missing_snapshots:
        missing = {
            "workers": missing_workers,
            "results": missing_results,
            "profiles": missing_profiles,
            "context_snapshots": missing_snapshots,
        }
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="blocked",
            summary=f"Readonly fanout execution evidence is incomplete: {missing}.",
            recommended_action=(
                "Rerun `asteria execute` for the subagent task so each fanout child records "
                "worker, result, runtime profile, and context snapshot evidence."
            ),
            evidence_refs=[item for item in [*evidence_refs, *child_evidence_refs] if item][:10],
        )
    if bad_statuses:
        if _is_readonly_write_gate_probe(plan, run_dirs) and _readonly_write_gate_failures(
            bad_summaries
        ):
            return RuntimeReadinessCheck(
                name="subagent_readonly_fanout",
                status="ready",
                summary=(
                    "Readonly write-gate probe recorded expected blocked child write "
                    f"attempt(s): {bad_statuses}."
                ),
                evidence_refs=[item for item in [*evidence_refs, *child_evidence_refs] if item][
                    :10
                ],
            )
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="blocked",
            summary=f"Readonly fanout child worker(s) did not succeed: {bad_statuses}.",
            recommended_action=(
                "Run `asteria debug` or `asteria replan` so the parent loop consumes the "
                "fanout child failure."
            ),
            evidence_refs=[item for item in [*evidence_refs, *child_evidence_refs] if item][:10],
        )
    if missing_validation:
        validated_plan = _latest_validated_readonly_fanout_plan(run_dirs, validator)
        validated_plan_id = (
            str(validated_plan.get("subagent_child_plan_id") or "") if validated_plan else ""
        )
        validated_run_id = str(validated_plan.get("run_id") or "") if validated_plan else ""
        plan_run_id = str(plan.get("run_id") or "")
        if validated_plan_id and (validated_plan_id, validated_run_id) != (plan_id, plan_run_id):
            return RuntimeReadinessCheck(
                name="subagent_readonly_fanout",
                status="ready",
                summary=(
                    "Readonly fanout has prior validated child evidence; latest fanout "
                    f"succeeded without validation refs: {missing_validation}."
                ),
                evidence_refs=[validated_plan_id, *child_evidence_refs][:10],
            )
        return RuntimeReadinessCheck(
            name="subagent_readonly_fanout",
            status="review",
            summary=f"Readonly fanout child worker(s) succeeded without validation refs: {missing_validation}.",
            recommended_action="Rerun fanout children with verification enabled before widening validation.",
            evidence_refs=[item for item in [*evidence_refs, *child_evidence_refs] if item][:10],
        )
    return RuntimeReadinessCheck(
        name="subagent_readonly_fanout",
        status="ready",
        summary=(
            f"Readonly fanout recorded {len(children)}/{len(children)} child worker(s), "
            f"cost model_calls={total_model_calls}, tool_calls={total_tool_calls}."
        ),
        evidence_refs=[item for item in [*evidence_refs, *child_evidence_refs] if item][:10],
    )


def _readonly_fanout_boundary_error(plan: dict[str, Any]) -> str | None:
    if str(plan.get("scheduling_strategy") or "") != "parallel_readonly_safe":
        return "plan is not using parallel_readonly_safe scheduling"
    if str(plan.get("parallel_safety") or "") != "readonly":
        return "plan is not marked readonly"
    write_tools = {"write_file", "apply_patch", "restore_backup"}
    for child in plan.get("child_tasks") or []:
        if not isinstance(child, dict):
            return "child task is malformed"
        child_id = str(child.get("child_task_id") or child.get("task_id") or "unknown")
        if child.get("write_allowed") is True:
            return f"child `{child_id}` allows writes"
        if child.get("write_scope"):
            return f"child `{child_id}` has write scope"
        if set(child.get("allowed_tools") or []) & write_tools:
            return f"child `{child_id}` exposes write tools"
        if str(child.get("parallel_safety") or "") != "readonly":
            return f"child `{child_id}` is not marked readonly"
    return None


def _candidate_promotion_safety_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    promotions = _latest_candidate_promotions(run_dirs, validator)
    if not promotions:
        return RuntimeReadinessCheck(
            name="candidate_promotion_safety",
            status="ready",
            summary="No candidate promotion queue evidence is pending.",
        )
    merge_blocked = [
        item
        for item in promotions
        if isinstance(item.get("merge_gate"), dict) and item["merge_gate"].get("ok") is False
    ]
    if merge_blocked:
        refs = [str(item.get("promotion_id") or "") for item in merge_blocked]
        violations = [
            str(violation)
            for item in merge_blocked
            for violation in (item.get("merge_gate") or {}).get("violations") or []
        ]
        return RuntimeReadinessCheck(
            name="candidate_promotion_safety",
            status="blocked",
            summary=(
                "Candidate promotion merge gate blocked promotion: "
                + "; ".join(violations[:4])
            ),
            recommended_action=(
                "Resolve merge gate violations or discard the blocked candidate before "
                "widening disjoint write workers."
            ),
            evidence_refs=refs[:8],
        )
    failed = [
        item
        for item in promotions
        if str(item.get("status") or "") in {"blocked", "promotion_failed"}
    ]
    if failed:
        refs = [str(item.get("promotion_id") or "") for item in failed]
        return RuntimeReadinessCheck(
            name="candidate_promotion_safety",
            status="blocked",
            summary="Candidate promotion queue contains blocked or failed promotion entries.",
            recommended_action=(
                "Run `asteria promotions retry`, `asteria promotions reject`, or "
                "`asteria promotions discard` before enabling broader write concurrency."
            ),
            evidence_refs=refs[:8],
        )
    recovered = [
        item
        for item in promotions
        if str(item.get("status") or "") in {"rejected", "discarded"}
    ]
    pending = [
        item
        for item in promotions
        if str(item.get("status") or "")
        in {"queued", "pending_manual_approval", "auto_approved", "approved"}
    ]
    if pending:
        refs = [str(item.get("promotion_id") or "") for item in pending]
        return RuntimeReadinessCheck(
            name="candidate_promotion_safety",
            status="review",
            summary=f"Candidate promotion queue has {len(pending)} unresolved promotion(s).",
            recommended_action=(
                "Settle candidate promotions with `asteria promotions list` and approve, "
                "promote, reject, or discard them before disjoint write fanout."
            ),
            evidence_refs=refs[:8],
        )
    return RuntimeReadinessCheck(
        name="candidate_promotion_safety",
        status="ready",
        summary=(
            "Candidate promotions are settled and merge gates did not block."
            if not recovered
            else f"Candidate promotions are settled after {len(recovered)} recovery action(s)."
        ),
        evidence_refs=[str(item.get("promotion_id") or "") for item in promotions[:8]],
    )


def _subagent_disjoint_write_gate_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> RuntimeReadinessCheck:
    plan = _latest_disjoint_write_plan(run_dirs, validator)
    if not plan:
        return RuntimeReadinessCheck(
            name="subagent_disjoint_write_gate",
            status="ready",
            summary="No disjoint write child plan requires gate evidence yet.",
        )
    plan_id = str(plan.get("subagent_child_plan_id") or "")
    children = [item for item in plan.get("child_tasks") or [] if isinstance(item, dict)]
    if len(children) <= 1:
        return RuntimeReadinessCheck(
            name="subagent_disjoint_write_gate",
            status="review",
            summary="Disjoint write child plan does not contain multiple child write tasks.",
            recommended_action="Regenerate the child plan before considering disjoint write fanout.",
            evidence_refs=[plan_id],
        )
    gate_tasks = [_disjoint_child_gate_task(child) for child in children]
    result = DisjointWriteGate().evaluate(
        gate_tasks,
        promotions=_latest_candidate_promotions(run_dirs, validator),
        require_candidate_promotions=True,
    )
    if not result.ok:
        return RuntimeReadinessCheck(
            name="subagent_disjoint_write_gate",
            status="ready",
            summary=(
                "Disjoint write fanout gate blocked unsafe scheduling as expected: "
                + "; ".join(result.violations[:4])
            ),
            evidence_refs=[plan_id, *result.blocked_task_ids][:8],
        )
    return RuntimeReadinessCheck(
        name="subagent_disjoint_write_gate",
        status="ready",
        summary=(
            f"Disjoint write fanout gate allows {len(result.allowed_task_ids)} child "
            "write worker(s); real parallel execution remains gated."
        ),
        evidence_refs=[plan_id, *result.allowed_task_ids][:8],
    )


def _disjoint_child_gate_task(child: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(child.get("child_task_id") or child.get("task_id") or "unknown"),
        "parent_task_id": str(child.get("task_id") or ""),
        "parallel_safety": str(child.get("parallel_safety") or ""),
        "write_scope": [str(item) for item in child.get("write_scope") or []],
        "completion_contract": {
            "requires_changed_artifact": bool(child.get("write_scope")),
            "requires_verification": isinstance(child.get("verification_expectation"), dict),
            "allows_expected_failure": False,
        },
    }


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
    recovered = _latest_successful_task_execution_after(
        run_dirs,
        validator,
        run_id=str(latest_plan.get("run_id") or "") or None,
        task_id=str(latest_plan.get("task_id") or "") or None,
        created_at=str(latest_plan.get("created_at") or ""),
    )
    if recovered:
        return RuntimeReadinessCheck(
            name="observation_next_action",
            status="ready",
            summary="Failed observations are covered by later successful task execution evidence.",
            evidence_refs=[str(recovered.get("evidence_id") or "")],
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
    catalog = _capability_catalog_states(run_dirs)
    if not catalog["selected"] and not catalog["visible"]:
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
    selected = catalog["selected"]
    unexpected = sorted(item for item in actual if not _capability_matches_any(item, selected))
    if unexpected:
        visible_unselected = sorted(
            item for item in unexpected if _capability_matches_any(item, catalog["visible"])
        )
        blocked = sorted(
            item for item in unexpected if _capability_matches_any(item, catalog["blocked"])
        )
        missing = sorted(
            item
            for item in unexpected
            if not _capability_matches_any(item, catalog["visible"])
        )
        summary_parts = []
        if visible_unselected:
            summary_parts.append(
                "visible but not selected: " + ", ".join(visible_unselected[:3])
            )
        if blocked:
            summary_parts.append("catalog-blocked but invoked: " + ", ".join(blocked[:3]))
        if missing:
            summary_parts.append("missing from catalog: " + ", ".join(missing[:3]))
        summary = (
            "Actual capability selections are not fully aligned with task capability catalogs"
            + (": " + "; ".join(summary_parts) if summary_parts else ".")
        )
        return RuntimeReadinessCheck(
            name="capability_selection",
            status="review",
            summary=summary,
            recommended_action=(
                "Inspect `agent_loop_dispatch.json` and `capability_decisions.jsonl`; "
                "either mark the invoked capability selected in the task catalog or explain why "
                "the model/runtime substituted it."
            ),
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
    decision_run_id = str(latest_decision.get("run_id") or "")
    execution = _latest_execution_for_decision(
        run_dirs,
        validator,
        decision_id,
        run_id=decision_run_id,
    )
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


def _capability_catalog_states(run_dirs: list[Path]) -> dict[str, set[str]]:
    states: dict[str, set[str]] = {
        "visible": set(),
        "selected": set(),
        "skipped": set(),
        "blocked": set(),
    }
    for run_dir in run_dirs[-20:]:
        path = run_dir / "agent_loop_dispatch.json"
        if path.exists():
            try:
                dispatch = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dispatch = {}
            for task in dispatch.get("task_dispatch", []) or []:
                catalog = task.get("capability_catalog") if isinstance(task, dict) else None
                if not isinstance(catalog, dict):
                    continue
                for entry in catalog.get("entries", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    capability = _capability_key(
                        entry.get("capability_type"),
                        entry.get("name"),
                    )
                    if not capability:
                        continue
                    if entry.get("visible"):
                        states["visible"].add(capability)
                    state = str(entry.get("selection_state") or "")
                    if state in states:
                        states[state].add(capability)
        task_plan_path = run_dir / "task_plan.json"
        if not task_plan_path.exists():
            continue
        try:
            task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for task in task_plan.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            for tool in task.get("allowed_tools") or []:
                capability = _capability_key("tool", tool)
                if not capability:
                    continue
                states["visible"].add(capability)
                states["selected"].add(capability)
    return states


def _selected_capabilities(run_dirs: list[Path]) -> set[str]:
    return _capability_catalog_states(run_dirs)["selected"]


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
            capability = _capability_key(
                item.get("capability_type") or "tool",
                item.get("capability") or item.get("name"),
            )
            if capability:
                actual.add(capability)
    return actual


def _capability_key(capability_type: Any, name: Any) -> str | None:
    capability_type_text = str(capability_type or "").strip()
    name_text = str(name or "").strip()
    if not capability_type_text or not name_text:
        return None
    return f"{capability_type_text}:{name_text}"


def _capability_matches_any(actual: str, catalog: set[str]) -> bool:
    if actual in catalog:
        return True
    if not actual.startswith("mcp:") or "/" not in actual:
        return False
    server_key = actual.split("/", 1)[0]
    return server_key in catalog


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
        if _is_readonly_write_gate_probe(result, run_dirs) and _readonly_write_gate_failures(
            [str(result.get("summary") or "")]
        ):
            return None
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


def _is_readonly_write_gate_probe(item: dict[str, Any], run_dirs: list[Path]) -> bool:
    run_id = str(item.get("run_id") or "")
    task_id = str(item.get("target_task_id") or item.get("task_id") or item.get("parent_task_id") or "")
    return "readonly_write_tool_blocked" in _validation_probe_ids_for_task(
        run_dirs,
        run_id,
        task_id,
    )


def _is_disjoint_write_gate_probe(item: dict[str, Any], run_dirs: list[Path]) -> bool:
    run_id = str(item.get("run_id") or "")
    task_id = str(item.get("target_task_id") or item.get("task_id") or item.get("parent_task_id") or "")
    return "disjoint_write_gate_blocks_unsafe_fanout" in _validation_probe_ids_for_task(
        run_dirs,
        run_id,
        task_id,
    )


def _validation_probe_ids_for_task(
    run_dirs: list[Path],
    run_id: str,
    task_id: str,
) -> set[str]:
    if not run_id:
        return set()
    for run_dir in run_dirs:
        if run_dir.name != run_id:
            continue
        task_plan_path = run_dir / "task_plan.json"
        if not task_plan_path.exists():
            return set()
        try:
            task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        for task in task_plan.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            if task_id and str(task.get("task_id") or "") != task_id:
                continue
            hints = task.get("runtime_profile_hints")
            hints = hints if isinstance(hints, dict) else {}
            return {str(item) for item in hints.get("validation_probe_ids") or [] if str(item)}
    return set()


def _readonly_write_gate_failures(summaries: list[str]) -> bool:
    if not summaries:
        return False
    return all("readonly fanout child cannot use write tool" in item.lower() for item in summaries)


def _execution_observation_check(
    run_dirs: list[Path],
    validator: SchemaValidator,
    decision: dict[str, Any],
    execution: dict[str, Any],
) -> RuntimeReadinessCheck | None:
    execution_id = str(execution.get("execution_id") or "")
    observation = _latest_observation_for_execution(run_dirs, validator, execution_id)
    if not observation:
        if _is_disjoint_write_gate_probe(execution, run_dirs):
            return None
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
        if _is_readonly_write_gate_probe(observation, run_dirs) and _readonly_write_gate_failures(
            [str(observation.get("summary") or "")]
        ):
            return None
        recovered = _latest_successful_task_execution_after(
            run_dirs,
            validator,
            run_id=str(observation.get("run_id") or "") or None,
            task_id=str(observation.get("task_id") or "") or None,
            created_at=str(observation.get("created_at") or ""),
        )
        if recovered:
            return None
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
    *,
    run_id: str | None = None,
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
            if run_id and str(item.get("run_id") or "") != run_id:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _latest_successful_task_execution_after(
    run_dirs: list[Path],
    validator: SchemaValidator,
    *,
    run_id: str | None,
    task_id: str | None,
    created_at: str,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "task_execution_evidence"):
            if run_id and str(item.get("run_id") or "") != run_id:
                continue
            if task_id and str(item.get("task_id") or "") != task_id:
                continue
            if str(item.get("status") or "") not in {"done", "succeeded"}:
                continue
            item_created = str(item.get("created_at") or "")
            if created_at and item_created < created_at:
                continue
            if latest is None or item_created >= latest_created:
                latest = item
                latest_created = item_created
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


def _worker_results_by_worker(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, dict[str, Any]]:
    store = JsonlStore(validator)
    results: dict[str, dict[str, Any]] = {}
    for run_dir in run_dirs:
        path = run_dir / "worker_results.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "worker_result"):
            worker_id = str(item.get("worker_invocation_id") or "")
            if worker_id:
                results[worker_id] = item
    return results


def _workers_for_parent(
    run_dirs: list[Path],
    validator: SchemaValidator,
    parent_worker_id: str,
) -> list[dict[str, Any]]:
    store = JsonlStore(validator)
    workers: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        path = run_dir / "workers.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "worker_invocation"):
            if str(item.get("parent_worker_invocation_id") or "") == parent_worker_id:
                workers.append(item)
    return workers


def _runtime_profiles_by_id(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, dict[str, Any]]:
    store = JsonlStore(validator)
    profiles: dict[str, dict[str, Any]] = {}
    for run_dir in run_dirs:
        path = run_dir / "runtime_profiles.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "runtime_profile"):
            profile_id = str(item.get("runtime_profile_id") or "")
            if profile_id:
                profiles[profile_id] = item
    return profiles


def _latest_readonly_fanout_plan(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "subagent_child_plans.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "subagent_child_plan"):
            if str(item.get("scheduling_strategy") or "") != "parallel_readonly_safe":
                continue
            children = [child for child in item.get("child_tasks") or [] if isinstance(child, dict)]
            if len(children) <= 1:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _latest_validated_readonly_fanout_plan(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        workers = _read_jsonl(run_dir / "workers.jsonl", "worker_invocation", validator)
        results = {
            str(item.get("worker_invocation_id") or ""): item
            for item in _read_jsonl(run_dir / "worker_results.jsonl", "worker_result", validator)
        }
        runtime_profiles = {
            str(item.get("runtime_profile_id") or ""): item
            for item in _read_jsonl(run_dir / "runtime_profiles.jsonl", "runtime_profile", validator)
        }
        snapshots = _read_jsonl(
            run_dir / "context_budget_snapshots.jsonl",
            "context_budget_snapshot",
            validator,
        )
        path = run_dir / "subagent_child_plans.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "subagent_child_plan"):
            if str(item.get("scheduling_strategy") or "") != "parallel_readonly_safe":
                continue
            children = [child for child in item.get("child_tasks") or [] if isinstance(child, dict)]
            parent_worker_id = str(item.get("worker_invocation_id") or "")
            if len(children) <= 1 or not parent_worker_id:
                continue
            if _readonly_fanout_boundary_error(item) is not None:
                continue
            child_workers = {
                str(worker.get("task_id") or ""): worker
                for worker in workers
                if str(worker.get("worker_kind") or "") == "subagent_readonly_child"
                and str(worker.get("parent_worker_invocation_id") or "") == parent_worker_id
            }
            ready = True
            for child in children:
                child_task_id = str(child.get("child_task_id") or child.get("task_id") or "")
                worker = child_workers.get(child_task_id)
                if not worker:
                    ready = False
                    break
                worker_id = str(worker.get("worker_invocation_id") or "")
                runtime_profile_id = str(worker.get("runtime_profile_id") or "")
                result = results.get(worker_id)
                if (
                    not result
                    or str(result.get("status") or "") != "succeeded"
                    or not list(result.get("validation_refs") or [])
                    or runtime_profile_id not in runtime_profiles
                    or not _has_context_snapshot(snapshots, runtime_profile_id, child_task_id)
                ):
                    ready = False
                    break
            created = str(item.get("created_at") or "")
            if ready and (latest is None or created >= latest_created):
                latest = item
                latest_created = created
    return latest


def _read_jsonl(path: Path, schema_name: str, validator: SchemaValidator) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return JsonlStore(validator).read_all(path, schema_name)


def _has_context_snapshot(
    snapshots: list[dict[str, Any]],
    runtime_profile_id: str,
    task_id: str,
) -> bool:
    return any(
        str(item.get("runtime_profile_id") or "") == runtime_profile_id
        and (not task_id or str(item.get("task_id") or "") == task_id)
        and str(item.get("scope") or "") in {"subagent_child", "task_context"}
        for item in snapshots
    )


def _latest_candidate_promotions(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> list[dict[str, Any]]:
    store = JsonlStore(validator)
    latest: dict[str, dict[str, Any]] = {}
    for run_dir in run_dirs:
        path = run_dir / "candidate_promotions.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "candidate_promotion"):
            promotion_id = str(item.get("promotion_id") or "")
            if promotion_id:
                latest[promotion_id] = item
    return [latest[key] for key in sorted(latest)]


def _latest_disjoint_write_plan(
    run_dirs: list[Path],
    validator: SchemaValidator,
) -> dict[str, Any] | None:
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "subagent_child_plans.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "subagent_child_plan"):
            if str(item.get("scheduling_strategy") or "") != (
                "parallel_disjoint_writes_after_merge_gate"
            ):
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
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
            if str(item.get("scope") or "") not in {"subagent_child", "task_context"}:
                continue
            if str(item.get("parent_worker_invocation_id") or "") != worker_id:
                continue
            created = str(item.get("created_at") or "")
            if latest is None or created >= latest_created:
                latest = item
                latest_created = created
    return latest


def _latest_context_budget_snapshot_for_runtime_profile(
    run_dirs: list[Path],
    validator: SchemaValidator,
    runtime_profile_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    if not runtime_profile_id:
        return None
    store = JsonlStore(validator)
    latest: dict[str, Any] | None = None
    latest_created = ""
    for run_dir in run_dirs:
        path = run_dir / "context_budget_snapshots.jsonl"
        if not path.exists():
            continue
        for item in store.read_all(path, "context_budget_snapshot"):
            if str(item.get("scope") or "") not in {"subagent_child", "task_context"}:
                continue
            if str(item.get("runtime_profile_id") or "") != runtime_profile_id:
                continue
            if task_id and str(item.get("task_id") or "") != task_id:
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
