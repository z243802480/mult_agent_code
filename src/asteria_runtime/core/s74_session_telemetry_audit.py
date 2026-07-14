"""S74 session telemetry and Studio/runtime consistency audit (CC / Codex aligned).

Reference products treat session process (turns, tools, elapsed) as trace evidence for
trust and regression analysis — not as universal Runtime hard stops. See ADR-0010.

Claude Code: continuous Session transcript + Inspector for raw evidence.
Codex: same-thread iteration with process visibility and failure explanation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand

AUDIT_MODE = "audit_only"

USER_PROGRESS_CONSISTENCY_CHECKS = frozenset(
    {
        "user_progress_protocol",
        "user_progress_semantic_contract",
        "main_thread_no_raw_model_delta",
        "inspector_model_delta_boundary",
    }
)

STUDIO_RUNTIME_CONSISTENCY_CHECKS = frozenset(
    USER_PROGRESS_CONSISTENCY_CHECKS
    | {
        "task_progress",
        "permission_or_result",
        "inspector_separation",
    }
)


def default_audit_policy() -> dict[str, Any]:
    return {
        "mode": AUDIT_MODE,
        "reference": {
            "claude_code": "Session transcript + Inspector separation",
            "codex": "Same-thread process evidence + scoped verification",
        },
        "adr": "docs/zh/adr/0010-open-agent-loop-and-evaluation-boundaries.md",
        "slo_thresholds": {
            "model_calls_max": 8,
            "repair_count_max": 2,
            "elapsed_total_seconds_max": 600,
        },
        "matrix_blocking": False,
    }


def audit_session_telemetry(
    unified: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    slot_id: str | None = None,
) -> dict[str, Any]:
    """Record CC/Codex-style session telemetry with SLO warnings (never blocks matrix)."""

    active_policy = policy or default_audit_policy()
    thresholds = active_policy.get("slo_thresholds") or {}
    slo_warnings: list[str] = []

    model_calls = unified.get("model_calls")
    if model_calls is not None:
        model_calls = int(model_calls)
        cap = int(thresholds.get("model_calls_max") or 0)
        if cap and model_calls > cap:
            slo_warnings.append(f"model_calls {model_calls} exceeds audit SLO {cap}")

    repair_count = unified.get("repair_count")
    if repair_count is not None:
        repair_count = int(repair_count)
        cap = int(thresholds.get("repair_count_max") or 0)
        if cap and repair_count > cap:
            slo_warnings.append(f"repair_count {repair_count} exceeds audit SLO {cap}")

    elapsed = unified.get("elapsed_total")
    if elapsed is not None:
        elapsed_seconds = float(elapsed)
        # Distinct name: `cap` above is an int (repair_count threshold); reusing it for a float cap
        # is what mypy flagged.
        cap_seconds = float(thresholds.get("elapsed_total_seconds_max") or 0)
        if cap_seconds and elapsed_seconds > cap_seconds:
            slo_warnings.append(
                f"elapsed_total {elapsed_seconds}s exceeds audit SLO {cap_seconds}s"
            )

    return {
        "mode": AUDIT_MODE,
        "slot_id": slot_id,
        "matrix_blocking": bool(active_policy.get("matrix_blocking")),
        "telemetry": {
            "model_calls": model_calls,
            "tool_calls": unified.get("tool_calls"),
            "repair_count": repair_count,
            "replan_count": unified.get("replan_count"),
            "elapsed_total": elapsed,
            "goal_completed": unified.get("goal_completed"),
        },
        "slo_warnings": slo_warnings,
        "slo_status": "pass_with_warnings" if slo_warnings else "pass",
    }


def audit_run_session_consistency(
    *,
    repo_root: Path,
    workspace: Path | None,
    run_id: str | None,
    manifest: Path | None = None,
) -> dict[str, Any]:
    """Run-scoped Studio benchmark audit — maps to matrix consistency fields."""

    if not workspace or not run_id:
        return {
            "user_progress_consistent": None,
            "studio_runtime_consistent": None,
            "reason": "missing_workspace_or_run_id",
        }
    runs_root = workspace / ".asteria" / "runs"
    run_dir = runs_root / run_id
    if not run_dir.is_dir():
        return {
            "user_progress_consistent": False,
            "studio_runtime_consistent": False,
            "reason": "run_dir_missing",
            "run_dir": str(run_dir),
        }

    manifest_path = manifest or repo_root / "benchmarks" / "studio_user_tasks.json"
    result = StudioBenchmarkCommand(
        root=repo_root,
        manifest=manifest_path,
        run_id=run_id,
        runs_root=runs_root,
    ).run()
    checks = {check["name"]: check for check in result.checks}
    user_progress_ok = all(
        checks.get(name, {}).get("ok") for name in USER_PROGRESS_CONSISTENCY_CHECKS
    )
    studio_runtime_ok = all(
        checks.get(name, {}).get("ok") for name in STUDIO_RUNTIME_CONSISTENCY_CHECKS
    )
    return {
        "user_progress_consistent": user_progress_ok,
        "studio_runtime_consistent": studio_runtime_ok,
        "score": result.score,
        "scope": result.scope,
        "checks": result.checks,
        "run_dir": str(run_dir),
    }


def apply_session_audit_to_unified(
    unified: dict[str, Any],
    *,
    repo_root: Path,
    workspace: Path | None,
    run_id: str | None,
    policy: dict[str, Any] | None = None,
    slot_id: str | None = None,
    manifest: Path | None = None,
) -> dict[str, Any]:
    """Merge telemetry + consistency audit into unified matrix fields."""

    telemetry = audit_session_telemetry(unified, policy=policy, slot_id=slot_id)
    consistency = audit_run_session_consistency(
        repo_root=repo_root,
        workspace=workspace,
        run_id=run_id,
        manifest=manifest,
    )
    if consistency.get("user_progress_consistent") is not None:
        unified["user_progress_consistent"] = consistency["user_progress_consistent"]
    if consistency.get("studio_runtime_consistent") is not None:
        unified["studio_runtime_consistent"] = consistency["studio_runtime_consistent"]
    unified["session_audit"] = {
        "telemetry": telemetry,
        "consistency": {
            key: consistency.get(key)
            for key in (
                "user_progress_consistent",
                "studio_runtime_consistent",
                "score",
                "scope",
                "reason",
            )
        },
    }
    if telemetry.get("slo_warnings"):
        unified.setdefault("slo_warnings", []).extend(telemetry["slo_warnings"])
    return unified
