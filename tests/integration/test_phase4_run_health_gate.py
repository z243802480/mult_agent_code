from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.core.run_health_audit import evaluate_run_health_from_manifest


GATE = json.loads(Path("benchmarks/phase4_run_health_gate.json").read_text(encoding="utf-8"))


def test_phase4_run_health_gate_flags_legacy_s7_signoff_run() -> None:
    run_dir = Path(GATE["unhealthy_fixture_run"])
    if not run_dir.exists():
        return

    audit = evaluate_run_health_from_manifest(GATE, run_dir)

    assert audit["ok"] is False
    assert audit["status"] == "fail"
    assert audit["sample"]["user_progress_bytes"] > GATE["thresholds"]["max_user_progress_bytes"]
    assert audit["sample"]["replan_task_count"] > GATE["thresholds"]["max_replan_tasks"]


def test_phase4_run_health_gate_passes_s13_clean_run_when_present() -> None:
    run_dir = Path(GATE.get("healthy_fixture_run", ""))
    if not run_dir.exists():
        return

    audit = evaluate_run_health_from_manifest(GATE, run_dir)

    assert audit["ok"] is True
    assert audit["status"] == "pass"
    assert audit["sample"]["run_status"] == "completed"


def test_phase4_run_health_gate_manifest_is_wired() -> None:
    assert GATE["contract_test"] == "tests/integration/test_phase4_run_health_gate.py"
    assert GATE["thresholds"]["max_user_progress_events"] == 2000
