from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.north_star import NorthStarStore
from tests.unit.test_accept_command import _workspace_ready_for_accept

pytestmark = pytest.mark.workflow

GATE = json.loads(Path("benchmarks/phase6d_goal_queue_gate.json").read_text(encoding="utf-8"))


def test_phase6d_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "4"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    scope = GATE["queue_scope"]
    assert scope["silent_auto_goal"] is False
    assert scope["requires_continue_hint"] is True


def test_accept_seeds_queue_and_suggests_continue(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    NorthStarStore(root).create_default(
        title="Goal queue",
        statement="Bounded slices",
        milestone_titles=["Slice A", "Slice B", "Slice C"],
    )

    result = AcceptCommand(root, skip_review=True).run()

    assert result.accepted is True
    queue = GoalQueueStore(root).read()
    assert queue is not None
    done_items = [item for item in queue["items"] if item["status"] == "done"]
    pending_items = [item for item in queue["items"] if item["status"] == "pending"]
    assert len(done_items) == 1
    assert run_dir.name in done_items[0]["linked_run_ids"]
    assert pending_items
    assert result.recommended_next_command is not None
    assert "Slice B" in result.recommended_next_command
    assert any("Continue North Star" in action for action in result.next_actions)

    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("title") == "North Star 下一条 slice" for event in progress)
