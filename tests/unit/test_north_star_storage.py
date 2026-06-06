from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_north_star_create_default_validates_against_schema(tmp_path: Path) -> None:
    validator = SchemaValidator(schema_dir())
    store = NorthStarStore(tmp_path, validator)
    path = store.create_default(
        title="Harness MVP 稳定",
        statement="本地优先 harness 可验证交付",
    )

    assert path.exists()
    data = store.read()
    assert data is not None
    assert data["title"] == "Harness MVP 稳定"
    assert data["north_star_id"] == "ns-0001"
    assert len(data["milestones"]) == 3
    assert data["milestones"][0]["status"] == "in_progress"


def test_north_star_link_run_updates_active_milestone(tmp_path: Path) -> None:
    validator = SchemaValidator(schema_dir())
    store = NorthStarStore(tmp_path, validator)
    store.create_default(title="Goal", statement="Statement")

    first = store.link_run("run-0001")
    assert first is not None
    assert first["linked_run_ids"] == ["run-0001"]
    assert first["status"] == "in_progress"

    for run_id in ("run-0002", "run-0003"):
        store.link_run(run_id)

    data = store.read()
    assert data is not None
    milestone = data["milestones"][0]
    assert milestone["linked_run_ids"] == ["run-0001", "run-0002", "run-0003"]
    assert milestone["status"] == "completed"


def test_north_star_summary_for_status(tmp_path: Path) -> None:
    store = NorthStarStore(tmp_path)
    store.create_default(title="North goal", statement="Long horizon")

    summary = store.summary_for_status()

    assert summary is not None
    assert summary["title"] == "North goal"
    assert summary["active_milestone"] == "Harness 会话 MVP 稳定"
    assert summary["milestone_count"] == 3
    assert summary["completed_milestones"] == 0


def test_init_command_creates_north_star_when_title_provided(tmp_path: Path) -> None:
    InitCommand(
        tmp_path,
        north_star_title="My north star",
        north_star_statement="Deliver verified artifacts",
    ).run()

    store = NorthStarStore(tmp_path)
    assert store.exists()
    data = store.read()
    assert data is not None
    assert data["title"] == "My north star"
    assert data["statement"] == "Deliver verified artifacts"
