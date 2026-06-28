from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.status_command import StatusCommand


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
