from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def latest_real_provider_matrix(agent_dir: Path) -> dict[str, Any]:
    """Return a compact summary for the latest real-provider P0 matrix run."""

    matrix_dir = agent_dir / "verification" / "real_provider_matrix"
    if not matrix_dir.exists():
        return {}
    candidates = _matrix_candidates(matrix_dir)
    if not candidates:
        return {}
    _is_real, _created_at, _modified, path, summary = max(
        candidates,
        key=lambda item: (item[0], item[1], item[2], item[3].as_posix()),
    )
    latest = summarize_real_provider_matrix(summary, path)
    latest["trend"] = summarize_real_provider_matrix_trend(
        [
            {"summary": item_summary, "path": item_path}
            for is_real, _created, _modified, item_path, item_summary in sorted(
                candidates,
                key=lambda item: (item[1], item[2], item[3].as_posix()),
                reverse=True,
            )
            if is_real
        ][:5]
    )
    return latest


def summarize_real_provider_matrix_trend(samples: list[dict[str, Any]]) -> dict[str, Any]:
    real_samples = [
        sample
        for sample in samples
        if _matrix_provider_mode(
            sample.get("summary") if isinstance(sample.get("summary"), dict) else {},
            sample.get("path") if isinstance(sample.get("path"), Path) else None,
        )
        == "real"
    ]
    by_case: dict[str, dict[str, Any]] = {}
    for sample in real_samples:
        summary = sample.get("summary") if isinstance(sample.get("summary"), dict) else {}
        summary_path = sample.get("path") if isinstance(sample.get("path"), Path) else None
        created_at = str(summary.get("created_at") or "")
        duration = _number(summary.get("duration_seconds"))
        for case in summary.get("cases") or []:
            if not isinstance(case, dict):
                continue
            name = str(case.get("name") or "unknown")
            item = by_case.setdefault(
                name,
                {
                    "sample_count": 0,
                    "pass_count": 0,
                    "fail_count": 0,
                    "durations_seconds": [],
                    "model_call_counts": [],
                    "strong_model_calls": [],
                    "task_execution_model_calls": [],
                    "task_repair_model_calls": [],
                    "run_review_model_calls": [],
                    "budget_repair_attempts": [],
                    "slim_model_calls": [],
                    "retry_classifications": {},
                    "latest": {},
                },
            )
            case_metrics = _matrix_case_metrics(case)
            item["sample_count"] += 1
            if case.get("ok") is True:
                item["pass_count"] += 1
            else:
                item["fail_count"] += 1
            if duration is not None:
                item["durations_seconds"].append(duration)
            for key in [
                "model_call_count",
                "strong_model_calls",
                "task_execution_model_calls",
                "task_repair_model_calls",
                "run_review_model_calls",
                "budget_repair_attempts",
                "slim_model_calls",
            ]:
                item[f"{key}s" if key == "model_call_count" else key].append(
                    int(case_metrics.get(key) or 0)
                )
            classification = classify_matrix_case_retry(case)
            classifications = item["retry_classifications"]
            classifications[classification] = classifications.get(classification, 0) + 1
            if not item["latest"]:
                item["latest"] = {
                    "created_at": created_at,
                    "summary_path": str(summary_path) if summary_path else None,
                    "ok": bool(case.get("ok")),
                    "retry_classification": classification,
                    **case_metrics,
                }
    compact_cases = {
        name: _compact_trend_case(item) for name, item in sorted(by_case.items())
    }
    warnings = _trend_warnings(compact_cases)
    return {
        "schema_version": "0.1.0",
        "sample_count": len(real_samples),
        "case_count": len(compact_cases),
        "provider_mode": "real",
        "cases": compact_cases,
        "warnings": warnings,
    }


def summarize_real_provider_matrix(
    summary: dict[str, Any],
    summary_path: Path | None = None,
) -> dict[str, Any]:
    cases = [item for item in summary.get("cases") or [] if isinstance(item, dict)]
    failed_cases = [case for case in cases if case.get("ok") is not True]
    latest_case = failed_cases[-1] if failed_cases else (cases[-1] if cases else {})
    route = str(latest_case.get("route") or "unknown") if latest_case else "unknown"
    reason = str(latest_case.get("reason") or "No reason recorded.") if latest_case else ""
    evidence_refs = [str(ref) for ref in latest_case.get("evidence_refs") or []][:5]
    agent_loop_cases = [
        case.get("agent_loop") for case in cases if isinstance(case.get("agent_loop"), dict)
    ]
    recorded_agent_loops = [
        loop for loop in agent_loop_cases if str(loop.get("status") or "") == "recorded"
    ]
    recovery_required = [
        loop for loop in recorded_agent_loops if loop.get("recovery_required") is True
    ]
    recovery_satisfied = [
        loop for loop in recovery_required if loop.get("recovery_satisfied") is True
    ]
    context_strategy_cases = [
        case.get("context_strategy")
        for case in cases
        if isinstance(case.get("context_strategy"), dict)
    ]
    recorded_context = [
        item for item in context_strategy_cases if str(item.get("status") or "") == "recorded"
    ]
    context_modes = _sum_nested_counts(recorded_context, "context_modes")
    fast_path_task_kinds = _sum_nested_counts(recorded_context, "fast_path_task_kinds")
    context_mode_recorded = sum(int(item.get("context_mode_recorded") or 0) for item in recorded_context)
    slim_model_calls = sum(int(item.get("slim_model_calls") or 0) for item in recorded_context)
    model_call_count = sum(int(item.get("model_call_count") or 0) for item in recorded_context)
    strong_model_calls = sum(int(item.get("strong_model_calls") or 0) for item in recorded_context)
    failed_model_calls = sum(int(item.get("failed_model_calls") or 0) for item in recorded_context)
    task_execution_model_calls = sum(
        int(item.get("task_execution_model_calls") or 0) for item in recorded_context
    )
    task_repair_model_calls = sum(
        int(item.get("task_repair_model_calls") or 0) for item in recorded_context
    )
    run_review_model_calls = sum(
        int(item.get("run_review_model_calls") or 0) for item in recorded_context
    )
    repair_attempts = sum(
        int(loop.get("budget_repair_attempts") or 0) for loop in recorded_agent_loops
    )
    average_context_tokens = _weighted_average_context_tokens(recorded_context)
    failed_summaries = [
        {
            "name": case.get("name"),
            "task_kind": case.get("task_kind"),
            "route": case.get("route"),
            "reason": case.get("reason"),
            "failure_summary": case.get("failure_summary"),
            "evidence_refs": [str(ref) for ref in case.get("evidence_refs") or []][:5],
        }
        for case in failed_cases[:5]
    ]
    result: dict[str, Any] = {
        "matrix": summary.get("matrix"),
        "matrix_preset": summary.get("matrix_preset"),
        "provider_mode": _matrix_provider_mode(summary, summary_path),
        "created_at": summary.get("created_at"),
        "ok": bool(summary.get("ok")),
        "case_count": int(summary.get("case_count") or len(cases)),
        "passed": int(summary.get("passed") or 0),
        "failed": int(summary.get("failed") or len(failed_cases)),
        "latest_case": latest_case.get("name") if latest_case else None,
        "latest_task_kind": latest_case.get("task_kind") if latest_case else None,
        "latest_route": route,
        "latest_reason": reason,
        "latest_evidence_refs": evidence_refs,
        "agent_loop_case_count": len(agent_loop_cases),
        "agent_loop_recorded": len(recorded_agent_loops),
        "recovery_required": len(recovery_required),
        "recovery_satisfied": len(recovery_satisfied),
        "context_strategy_case_count": len(context_strategy_cases),
        "context_strategy_recorded": len(recorded_context),
        "context_modes": context_modes,
        "fast_path_task_kinds": fast_path_task_kinds,
        "context_mode_recorded": context_mode_recorded,
        "slim_model_calls": slim_model_calls,
        "model_call_count": model_call_count,
        "strong_model_calls": strong_model_calls,
        "failed_model_calls": failed_model_calls,
        "task_execution_model_calls": task_execution_model_calls,
        "task_repair_model_calls": task_repair_model_calls,
        "run_review_model_calls": run_review_model_calls,
        "budget_repair_attempts": repair_attempts,
        "average_context_estimated_tokens": average_context_tokens,
        "failed_cases": failed_summaries,
    }
    if summary_path is not None:
        result["summary_path"] = str(summary_path)
    return result


def classify_matrix_case_retry(case: dict[str, Any]) -> str:
    metrics = _matrix_case_metrics(case)
    name = str(case.get("name") or "")
    if case.get("ok") is not True:
        if metrics["budget_repair_attempts"] > 0 or metrics["task_repair_model_calls"] > 0:
            return "failed_after_repair"
        return "failed_case"
    if metrics["budget_repair_attempts"] > 0 or metrics["task_repair_model_calls"] > 0:
        return "repair_loop"
    if metrics["failed_model_calls"] > 0:
        return "model_call_failure"
    if metrics["run_review_model_calls"] > 0:
        return "review_escalation"
    if name == "single_file_bugfix":
        kinds = metrics["fast_path_task_kinds"]
        if kinds and "single_file_bugfix" not in kinds:
            return "fast_path_mismatch"
        if metrics["task_execution_model_calls"] > 1:
            return "extra_execution_without_repair"
        return "stable_single_execution"
    if metrics["task_execution_model_calls"] > 1:
        return "multiple_execution_calls"
    return "stable"


def real_provider_matrix_text_lines(matrix: dict[str, Any]) -> list[str]:
    if not matrix:
        return []
    lines = [
        "Latest real-provider matrix: "
        f"{matrix.get('passed', 0)}/{matrix.get('case_count', 0)} passed "
        f"(ok={matrix.get('ok', False)})",
        "  route: "
        f"{matrix.get('latest_route', 'unknown')} "
        f"task={matrix.get('latest_task_kind', 'unknown')} "
        f"case={matrix.get('latest_case', 'unknown')}",
        f"  reason: {matrix.get('latest_reason') or 'No reason recorded.'}",
    ]
    if matrix.get("agent_loop_case_count"):
        lines.append(
            "  agent loop: "
            f"{matrix.get('agent_loop_recorded', 0)}/{matrix.get('agent_loop_case_count', 0)} recorded, "
            f"recovery {matrix.get('recovery_satisfied', 0)}/{matrix.get('recovery_required', 0)} covered"
        )
    if matrix.get("context_strategy_case_count"):
        lines.append(
            "  context: "
            f"{matrix.get('context_strategy_recorded', 0)}/{matrix.get('context_strategy_case_count', 0)} recorded, "
            f"slim {matrix.get('slim_model_calls', 0)}/{matrix.get('model_call_count', 0)} calls, "
            f"modes={matrix.get('context_modes') or {}}"
        )
        lines.append(
            "  models: "
            f"strong={matrix.get('strong_model_calls', 0)}, "
            f"task_execution={matrix.get('task_execution_model_calls', 0)}, "
            f"task_repair={matrix.get('task_repair_model_calls', 0)}, "
            f"run_review={matrix.get('run_review_model_calls', 0)}, "
            f"repair_attempts={matrix.get('budget_repair_attempts', 0)}"
        )
    trend = matrix.get("trend") if isinstance(matrix.get("trend"), dict) else {}
    trend_cases = trend.get("cases") if isinstance(trend.get("cases"), dict) else {}
    if trend_cases:
        lines.append(
            "  trend: "
            f"{trend.get('sample_count', 0)} real sample(s), "
            f"cases={', '.join(sorted(str(name) for name in trend_cases)[:4])}"
        )
        bugfix = trend_cases.get("single_file_bugfix")
        if isinstance(bugfix, dict):
            lines.append(
                "  single_file_bugfix: "
                f"task_execution avg={bugfix.get('task_execution_model_calls_avg')}, "
                f"max={bugfix.get('task_execution_model_calls_max')}, "
                f"repair max={bugfix.get('budget_repair_attempts_max')}, "
                f"class={bugfix.get('latest_retry_classification')}"
            )
        for warning in trend.get("warnings") or []:
            lines.append(f"  trend warning: {warning}")
    evidence_refs = matrix.get("latest_evidence_refs") or []
    if evidence_refs:
        lines.append(f"  evidence: {', '.join(str(ref) for ref in evidence_refs[:3])}")
    summary_path = matrix.get("summary_path")
    if summary_path:
        lines.append(f"  summary: {summary_path}")
    failed_cases = matrix.get("failed_cases") or []
    if failed_cases:
        lines.append("  failed routes:")
        for case in failed_cases[:3]:
            lines.append(
                "    - "
                f"{case.get('name', 'unknown')}: "
                f"{case.get('route', 'unknown')} "
                f"({case.get('failure_summary') or case.get('reason') or 'no summary'})"
            )
    return lines


def _sum_nested_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        raw = item.get(key)
        if not isinstance(raw, dict):
            continue
        for name, value in raw.items():
            try:
                counts[str(name)] = counts.get(str(name), 0) + int(value)
            except (TypeError, ValueError):
                continue
    return dict(sorted(counts.items()))


def _matrix_candidates(matrix_dir: Path) -> list[tuple[bool, str, float, Path, dict[str, Any]]]:
    candidates: list[tuple[bool, str, float, Path, dict[str, Any]]] = []
    for path in matrix_dir.glob("*/matrix_summary.json"):
        summary = _read_json(path)
        if not summary:
            continue
        created_at = str(summary.get("created_at") or "")
        is_real = _matrix_provider_mode(summary, path) == "real"
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        candidates.append((is_real, created_at, modified, path, summary))
    return candidates


def _matrix_case_metrics(case: dict[str, Any]) -> dict[str, Any]:
    context_strategy = case.get("context_strategy")
    context_strategy = context_strategy if isinstance(context_strategy, dict) else {}
    agent_loop = case.get("agent_loop")
    agent_loop = agent_loop if isinstance(agent_loop, dict) else {}
    fast_path = context_strategy.get("fast_path_task_kinds")
    purposes = context_strategy.get("purposes")
    purposes = purposes if isinstance(purposes, dict) else {}
    model_tiers = context_strategy.get("model_tiers")
    model_tiers = model_tiers if isinstance(model_tiers, dict) else {}
    purpose_context_modes = context_strategy.get("purpose_context_modes")
    purpose_context_modes = purpose_context_modes if isinstance(purpose_context_modes, dict) else {}
    return {
        "model_call_count": int(context_strategy.get("model_call_count") or 0),
        "strong_model_calls": _count_metric(context_strategy, "strong_model_calls")
        or _count_from_mapping(model_tiers, "strong"),
        "failed_model_calls": int(context_strategy.get("failed_model_calls") or 0),
        "task_execution_model_calls": _purpose_count(
            context_strategy,
            purposes,
            purpose_context_modes,
            "task_execution",
        ),
        "task_repair_model_calls": _purpose_count(
            context_strategy,
            purposes,
            purpose_context_modes,
            "task_repair",
        ),
        "run_review_model_calls": _purpose_count(
            context_strategy,
            purposes,
            purpose_context_modes,
            "run_review",
        ),
        "slim_model_calls": int(context_strategy.get("slim_model_calls") or 0),
        "budget_repair_attempts": int(agent_loop.get("budget_repair_attempts") or 0),
        "fast_path_task_kinds": fast_path if isinstance(fast_path, dict) else {},
    }


def _purpose_count(
    context_strategy: dict[str, Any],
    purposes: dict,
    purpose_context_modes: dict,
    purpose: str,
) -> int:
    explicit = _count_metric(context_strategy, f"{purpose}_model_calls")
    if explicit:
        return explicit
    from_purposes = _count_from_mapping(purposes, purpose)
    if from_purposes:
        return from_purposes
    modes = purpose_context_modes.get(purpose)
    if isinstance(modes, dict):
        return sum(_safe_int(value) for value in modes.values())
    return 0


def _count_metric(item: dict[str, Any], key: str) -> int:
    return _safe_int(item.get(key))


def _count_from_mapping(item: dict, key: str) -> int:
    return _safe_int(item.get(key))


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_trend_case(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_count": item["sample_count"],
        "pass_count": item["pass_count"],
        "fail_count": item["fail_count"],
        "duration_seconds_avg": _average(item["durations_seconds"]),
        "duration_seconds_max": _max_or_zero(item["durations_seconds"]),
        "model_call_count_avg": _average(item["model_call_counts"]),
        "model_call_count_max": _max_or_zero(item["model_call_counts"]),
        "strong_model_calls_avg": _average(item["strong_model_calls"]),
        "strong_model_calls_max": _max_or_zero(item["strong_model_calls"]),
        "task_execution_model_calls_avg": _average(item["task_execution_model_calls"]),
        "task_execution_model_calls_max": _max_or_zero(item["task_execution_model_calls"]),
        "task_repair_model_calls_max": _max_or_zero(item["task_repair_model_calls"]),
        "run_review_model_calls_max": _max_or_zero(item["run_review_model_calls"]),
        "budget_repair_attempts_max": _max_or_zero(item["budget_repair_attempts"]),
        "slim_model_calls_avg": _average(item["slim_model_calls"]),
        "retry_classifications": dict(sorted(item["retry_classifications"].items())),
        "latest_retry_classification": item["latest"].get("retry_classification"),
        "latest": item["latest"],
    }


def _trend_warnings(cases: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    bugfix = cases.get("single_file_bugfix")
    if bugfix:
        if int(bugfix.get("strong_model_calls_max") or 0) > 0:
            warnings.append("single_file_bugfix used strong model calls in recent matrix samples.")
        if int(bugfix.get("budget_repair_attempts_max") or 0) > 0:
            warnings.append("single_file_bugfix still entered repair in recent matrix samples.")
        if float(bugfix.get("task_execution_model_calls_avg") or 0.0) > 2.0:
            warnings.append("single_file_bugfix averages more than two execution model calls.")
    return warnings


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _average(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return round(sum(float(value) for value in values) / len(values), 3)


def _max_or_zero(values: list[float | int]) -> float | int:
    return max(values) if values else 0


def _weighted_average_context_tokens(items: list[dict[str, Any]]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0
    for item in items:
        average = item.get("average_context_estimated_tokens")
        weight = int(item.get("model_call_count") or 0)
        if not isinstance(average, (int, float)) or weight <= 0:
            continue
        weighted_sum += float(average) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _matrix_provider_mode(summary: dict[str, Any], path: Path | None = None) -> str:
    mode = str(summary.get("provider_mode") or "").strip().lower()
    if mode:
        return mode
    output_dir = str(summary.get("output_dir") or "").lower()
    path_text = path.as_posix().lower() if path is not None else ""
    if any(marker in output_dir or marker in path_text for marker in ("fake", "offline")):
        return "fake"
    return "real"
