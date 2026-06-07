from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from asteria_runtime.core.friction_contract import evaluate_friction


def test_harness_repeatability_pulse_skips_b6_by_default() -> None:
    root = Path(".").resolve()
    completed = subprocess.run(
        [sys.executable, "scripts/harness_repeatability_pulse.py", "--root", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    b6_step = next(step for step in report["steps"] if step["step"] == "b6_restricted_user_sim")
    assert b6_step.get("skipped") is True


def test_friction_contract_matches_s16_b6_targets() -> None:
    result = evaluate_friction({"decide": 0, "debug": 1, "resume": 0})
    assert result["ok"] is True
    over = evaluate_friction({"decide": 0, "debug": 3, "resume": 0})
    assert over["ok"] is False
    assert "debug" in over["violations"]
