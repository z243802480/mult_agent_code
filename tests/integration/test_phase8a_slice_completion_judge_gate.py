from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.models.fake import FakeModelClient
from tests.unit.test_accept_command import _workspace_ready_for_accept

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase8a_slice_completion_judge_gate.json").read_text(encoding="utf-8")
)


def test_phase8a_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "8"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    scope = GATE["judge_scope"]
    assert scope["rules_first"] is True
    assert scope["model_can_veto_only"] is True
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()


def test_accept_with_model_judge_persists_model_judge_field(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    store = NorthStarStore(root)
    store.create_default(title="Model judge", statement="Judge slice completion")
    north_star = store.read()
    assert north_star is not None
    north_star["slice_completion_policy"] = {"enable_model_judge": True}
    store.write(north_star)

    result = AcceptCommand(
        root,
        skip_review=True,
        model_client=FakeModelClient(),
    ).run()

    assert result.accepted is True
    eval_path = run_dir / "slice_completion_eval.json"
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    assert payload["slice_complete"] is True
    assert payload.get("model_judge") is not None
    assert payload["model_judge"]["mode"] in {"model", "deterministic"}
    assert payload["signals"].get("model_judge_pass") is True
