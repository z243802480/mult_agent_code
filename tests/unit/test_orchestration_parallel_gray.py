from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.core.orchestration_parallel_gray import (
    build_orchestration_parallel_decision_point,
    evaluate_orchestration_parallel_readiness,
)


def _write_spawn_evidence(path: Path, *, hit_rate: float, case_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "real",
                "summary": {"hit_rate": hit_rate, "case_count": case_count},
            }
        ),
        encoding="utf-8",
    )


def _write_route_evidence(path: Path, *, hit_rate: float, case_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "model",
                "summary": {"hit_rate": hit_rate, "case_count": case_count},
            }
        ),
        encoding="utf-8",
    )


def test_readiness_passes_with_eval_evidence(tmp_path: Path) -> None:
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")

    spawn = tmp_path / "spawn.json"
    route = tmp_path / "route.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
    )
    assert readiness.ready_for_decision_point is True
    assert readiness.ready_for_maintainer_probe is False


def test_readiness_requires_gray_drill_for_probe(tmp_path: Path) -> None:
    policy_doc = tmp_path / "docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md"
    policy_doc.parent.mkdir(parents=True)
    policy_doc.write_text("# policy", encoding="utf-8")
    spawn = tmp_path / "spawn.json"
    route = tmp_path / "route.json"
    _write_spawn_evidence(spawn, hit_rate=0.95, case_count=23)
    _write_route_evidence(route, hit_rate=0.9, case_count=10)

    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=spawn,
        route_evidence_path=route,
        gray_drill_ok=True,
    )
    assert readiness.ready_for_maintainer_probe is True


def test_decision_point_defaults_to_defer_without_drill(tmp_path: Path) -> None:
    readiness = evaluate_orchestration_parallel_readiness(
        root=tmp_path,
        policy={"agent_loop": {"parallel_writes": False}},
        spawn_evidence_path=tmp_path / "missing.json",
        route_evidence_path=tmp_path / "missing2.json",
    )
    decision = build_orchestration_parallel_decision_point(
        run_id="run-test",
        readiness=readiness,
    )
    assert decision["default_option_id"] == "defer"
    assert decision["recommended_option_id"] == "defer"
