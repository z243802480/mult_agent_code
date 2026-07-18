from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.status_command import StatusCommand


def test_status_text_surfaces_active_background_runs(tmp_path: Path, monkeypatch) -> None:
    # dogfood friction #1: a run started with --background lives in its own session, but `status`
    # reports the foreground session with no hint that the background run exists. When background
    # runs are active, the text must point the user to `asteria background status`.
    InitCommand(tmp_path).run()
    from asteria_runtime.commands import status_command as sc

    monkeypatch.setattr(sc, "background_run_projection", lambda root: {"running_count": 2})
    text = StatusCommand(tmp_path).run().to_text()
    assert "Background runs: 2 active" in text
    assert "asteria background status" in text


def test_status_text_omits_background_hint_when_none_active(tmp_path: Path, monkeypatch) -> None:
    # No noise when nothing is running in the background.
    InitCommand(tmp_path).run()
    from asteria_runtime.commands import status_command as sc

    monkeypatch.setattr(sc, "background_run_projection", lambda root: {"running_count": 0})
    text = StatusCommand(tmp_path).run().to_text()
    assert "Background runs:" not in text


def test_status_json_includes_long_horizon_projection(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    payload = StatusCommand(tmp_path).run().to_dict()

    long_horizon = payload["long_horizon"]
    assert long_horizon["opens_on"] == "2026-06-06"
    assert long_horizon["ready_for_implementation"] is True
    assert long_horizon["status"] == "ready_not_configured"
    assert "days_remaining" in long_horizon
    assert long_horizon["north_star_configured"] is False


def test_status_json_long_horizon_when_north_star_configured(tmp_path: Path) -> None:
    InitCommand(
        tmp_path,
        north_star_title="Harness north star",
        north_star_statement="Verified long-task delivery",
    ).run()

    payload = StatusCommand(tmp_path).run().to_dict()
    long_horizon = payload["long_horizon"]

    assert long_horizon["north_star_configured"] is True
    assert long_horizon["status"] == "configured"
    assert long_horizon["north_star"]["title"] == "Harness north star"
    assert long_horizon["north_star"]["active_milestone"] == "Harness 会话 MVP 稳定"


def test_north_star_schema_is_valid_json_schema() -> None:
    schema = json.loads(Path("schemas/north_star.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "NorthStar"
    assert "milestones" in schema["properties"]
