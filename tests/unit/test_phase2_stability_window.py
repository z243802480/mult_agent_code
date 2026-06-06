from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from asteria_runtime.core.phase2_stability_window import evaluate_stability_window, load_stability_window


def test_stability_window_observing_before_open_date() -> None:
    window = {
        "window_start": "2026-06-06",
        "window_days": 14,
        "opens_on": "2026-06-20",
        "required_signoffs": ["docs/zh/reports/S7-mvp-signoff-20260606.md"],
        "required_gate_manifests": ["benchmarks/phase2_mvp_gate.json"],
        "north_star_rfc": "docs/zh/plans/NORTH_STAR_RFC.md",
        "north_star_schema": "schemas/north_star.schema.json",
    }
    audit = evaluate_stability_window(
        window,
        repo_root=Path.cwd(),
        today=date(2026, 6, 10),
    )

    assert audit["status"] == "observing"
    assert audit["prerequisites_ok"] is True
    assert audit["days_remaining"] == 10
    assert audit["ready_for_implementation"] is False


def test_stability_window_ready_after_open_date() -> None:
    window = json.loads(
        Path("benchmarks/phase2_stability_window.json").read_text(encoding="utf-8")
    )
    audit = evaluate_stability_window(
        window,
        repo_root=Path.cwd(),
        today=date(2026, 6, 6),
    )

    assert audit["status"] == "ready_for_implementation"
    assert audit["ready_for_implementation"] is True
    assert audit["days_remaining"] == 0
    assert window["opens_on"] == "2026-06-06"


def test_stability_window_blocked_when_signoff_missing(tmp_path: Path) -> None:
    window = {
        "window_start": "2026-06-06",
        "window_days": 14,
        "opens_on": "2026-06-20",
        "required_signoffs": ["docs/zh/reports/missing-signoff.md"],
        "required_gate_manifests": [],
        "north_star_rfc": "docs/zh/plans/NORTH_STAR_RFC.md",
        "north_star_schema": "schemas/north_star.schema.json",
    }
    audit = evaluate_stability_window(window, repo_root=tmp_path, today=date(2026, 6, 20))

    assert audit["status"] == "blocked"
    assert audit["missing_signoffs"] == ["docs/zh/reports/missing-signoff.md"]


def test_load_stability_window_reads_repo_manifest() -> None:
    window = load_stability_window(Path.cwd())

    assert window["window_days"] == 14
    assert window["north_star_rfc"] == "docs/zh/plans/NORTH_STAR_RFC.md"
