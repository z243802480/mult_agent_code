from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.long_horizon_handoff import (
    build_and_persist_long_horizon_handoff,
    handoff_compact_projection,
    read_long_horizon_handoff,
)
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_handoff_compact_unavailable_before_accept(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    projection = handoff_compact_projection(tmp_path)
    assert projection["available"] is False


def test_build_and_persist_handoff_includes_continue_hint(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(schema_dir())
    store = NorthStarStore(tmp_path, validator)
    store.create_default(title="Queue handoff", statement="Continue after slice")
    store.write(store.read() or {})

    payload = build_and_persist_long_horizon_handoff(
        tmp_path,
        trigger_run_id="run-test",
        validator=validator,
        slice_completion_eval={
            "run_id": "run-test",
            "slice_complete": True,
            "summary": "本 slice 已达成完成契约。",
        },
        goal_queue_continue={
            "goal_text": "Next slice goal",
            "command": "goal 'Next slice goal'",
        },
    )
    assert payload["recommended_next_command"] == "goal 'Next slice goal'"
    stored = read_long_horizon_handoff(tmp_path, validator)
    assert stored is not None
    compact = handoff_compact_projection(tmp_path, validator)
    assert compact["available"] is True
    assert compact["continue_goal"] == "Next slice goal"
