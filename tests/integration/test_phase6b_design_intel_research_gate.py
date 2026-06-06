from __future__ import annotations

import json
from pathlib import Path


GATE = json.loads(
    Path("benchmarks/phase6b_design_intel_research_gate.json").read_text(encoding="utf-8")
)


def test_phase6b_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "2"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    bridge = GATE["bridge_scope"]
    assert bridge["session_agent_default_unchanged"] is True
    assert "product_research" in bridge["research_cli_types"]
    assert "documentation" in bridge["plan_pilot_types"]
