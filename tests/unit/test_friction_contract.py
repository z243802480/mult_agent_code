from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.friction_contract import evaluate_friction


GATE = json.loads(Path("benchmarks/phase4_friction_gate.json").read_text(encoding="utf-8"))


def test_friction_within_thresholds() -> None:
    result = evaluate_friction({"decide": 1, "debug": 2, "resume": 0})
    assert result["ok"] is True
    assert result["violations"] == []


def test_friction_violation_detected() -> None:
    result = evaluate_friction({"decide": 3, "debug": 0, "resume": 0})
    assert result["ok"] is False
    assert "decide" in result["violations"]


def test_friction_gate_thresholds_match_contract() -> None:
    thresholds = GATE["thresholds"]
    at_limit = evaluate_friction(
        {"decide": thresholds["decide"], "debug": thresholds["debug"], "resume": thresholds["resume"]},
        thresholds=thresholds,
    )
    assert at_limit["ok"] is True


def test_studio_server_maps_replan_to_continue() -> None:
    source = Path("studio/server.mjs").read_text(encoding="utf-8")
    assert 'replan: "continue"' in source
