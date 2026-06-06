from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_goal_queue_seeds_from_north_star_milestones(tmp_path: Path) -> None:
    NorthStarStore(tmp_path).create_default(
        title="Queue seed",
        statement="Seed from milestones",
        milestone_titles=["One", "Two"],
    )
    queue = GoalQueueStore(tmp_path).ensure_seeded_from_north_star()
    assert queue is not None
    assert len(queue["items"]) >= 2
    assert queue["items"][0]["status"] == "pending"


def test_mark_done_for_run_links_run_and_exposes_continue_hint(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = GoalQueueStore(tmp_path, validator)
    store.seed_goals(["First slice", "Second slice"], source="test")
    marked = store.mark_done_for_run("run-abc")
    assert marked is not None
    assert marked["status"] == "done"
    assert "run-abc" in marked["linked_run_ids"]
    hint = store.continue_hint()
    assert hint is not None
    assert hint["goal_text"] == "Second slice"
    assert "Second slice" in hint["command"]
