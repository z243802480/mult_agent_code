from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.core.phase2_stability_window import long_horizon_projection
from asteria_runtime.core.long_horizon_handoff import handoff_path, read_long_horizon_handoff
from asteria_runtime.core.north_star import NorthStarStore
from tests.unit.test_accept_command import _workspace_ready_for_accept

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase8b_long_horizon_handoff_gate.json").read_text(encoding="utf-8")
)


def test_phase8b_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "8"
    assert Path(GATE["depends_on_gate"]).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()


def test_accept_persists_long_horizon_handoff_and_status_projects_it(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    store = NorthStarStore(root)
    store.create_default(title="Handoff compact", statement="Cross-session summary")

    result = AcceptCommand(root, skip_review=True).run()
    assert result.accepted is True
    assert handoff_path(root).exists()
    handoff = read_long_horizon_handoff(root)
    assert handoff is not None
    assert handoff["trigger_run_id"] == run_dir.name
    assert handoff.get("narrative")

    compact = long_horizon_projection(root)["handoff_compact"]
    assert compact["available"] is True
    assert compact["trigger_run_id"] == run_dir.name
