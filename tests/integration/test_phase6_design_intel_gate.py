from __future__ import annotations

import json
from pathlib import Path


GATE = json.loads(Path("benchmarks/phase6_design_intel_gate.json").read_text(encoding="utf-8"))


def test_phase6_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    pilot = GATE["pilot_scope"]
    assert pilot["session_agent_default_unchanged"] is True
    assert "documentation" in pilot["research_types"]
