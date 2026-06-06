from __future__ import annotations

import json
from pathlib import Path


GATE = json.loads(Path("benchmarks/phase4_steady_iteration_gate.json").read_text(encoding="utf-8"))


def test_phase4_steady_iteration_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "4"
    assert Path(GATE["rhythm_doc"]).exists()
    assert Path(GATE["reference_brief"]).exists()
    assert Path(GATE["pulse_script"]).exists()
    assert Path(GATE["prune_script"]).exists()
    assert Path(GATE["beta_tasks"]).exists()
    assert "tests/unit/test_documentation_contracts.py" in GATE["contract_tests"]


def test_s16_reference_brief_exists_and_links_rhythm_doc() -> None:
    brief = Path(GATE["reference_brief"]).read_text(encoding="utf-8")
    rhythm = Path(GATE["rhythm_doc"]).read_text(encoding="utf-8")
    assert "S16" in brief
    assert "稳态迭代节奏" in brief or "steady" in brief.lower()
    assert "brief" in rhythm.lower() or "brief" in rhythm
    assert "steady_iteration_check" in rhythm
