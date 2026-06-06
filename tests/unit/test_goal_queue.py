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


def test_mark_done_prefers_linked_run_item(tmp_path: Path) -> None:
    store = GoalQueueStore(tmp_path)
    store.seed_goals(["First", "Second"], source="test")
    store.mark_in_progress("gq-0001")
    store.link_run_to_goal("gq-0001", "run-linked")
    marked = store.mark_done_for_run("run-linked")
    assert marked is not None
    assert marked["goal_id"] == "gq-0001"
    assert marked["status"] == "done"
    queue = store.read()
    assert queue is not None
    assert queue["items"][1]["status"] == "pending"


def test_release_in_progress_restores_pending(tmp_path: Path) -> None:
    store = GoalQueueStore(tmp_path)
    store.seed_goals(["Only slice"], source="test")
    store.mark_in_progress("gq-0001")
    released = store.release_in_progress("gq-0001")
    assert released is not None
    assert released["status"] == "pending"


def test_continue_hint_shell_quotes_goal_text(tmp_path: Path) -> None:
    store = GoalQueueStore(tmp_path)
    store.seed_goals(['Add "quotes" safely'], source="test")
    hint = store.continue_hint()
    assert hint is not None
    assert hint["command"].startswith("goal ")
    assert "quotes" in hint["command"]
