from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.core.long_horizon_completion import SLICE_COMPLETION_EVAL_FILENAME
from asteria_runtime.core.north_star import NorthStarStore
from tests.unit.test_accept_command import _workspace_ready_for_accept

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase6c_long_horizon_completion_gate.json").read_text(encoding="utf-8")
)


def test_phase6c_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "3"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["depends_on_signoff"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    scope = GATE["completion_scope"]
    assert scope["silent_auto_execute"] is False
    assert scope["evaluator_artifact"] == "slice_completion_eval.json"


def test_accept_writes_slice_completion_eval_and_user_progress(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    NorthStarStore(root).create_default(title="Completion contract", statement="Evaluate slices")

    result = AcceptCommand(root, skip_review=True).run()

    assert result.accepted is True
    eval_path = run_dir / SLICE_COMPLETION_EVAL_FILENAME
    assert eval_path.exists()
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    assert payload["slice_complete"] is True
    assert payload["signals"]["accepted_run"] is True
    assert payload["signals"]["review_pass"] is True

    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("title") == "本 slice 完成判定" for event in progress)


def test_status_long_horizon_includes_last_slice_completion(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    InitCommand(root).run()
    NorthStarStore(root).create_default(title="Status projection", statement="Project completion")
    AcceptCommand(root, skip_review=True).run()

    long_horizon = StatusCommand(root).run().to_dict()["long_horizon"]
    last = long_horizon.get("last_slice_completion")
    assert last is not None
    assert last["run_id"] == run_dir.name
    assert last["slice_complete"] is True
