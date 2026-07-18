"""Cross-attempt task progress digest (residual② persistence half).

Guards that a task's tool actions survive across attempts on disk, so a replan / pause-resume
carries forward "you already read X / ran Y" instead of re-reading from scratch — and that the first
attempt is byte-identical (no file → nothing injected).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from asteria_runtime.core.task_progress_digest import (
    _MAX_ENTRIES,
    load_task_progress,
    record_task_progress,
    render_prior_progress,
)


def _obs(tool_name: str, summary: str, ok: bool = True) -> SimpleNamespace:
    return SimpleNamespace(tool_name=tool_name, summary=summary, ok=ok)


def test_first_attempt_has_no_prior_progress(tmp_path: Path) -> None:
    # No file yet → nothing to carry → callers inject nothing (behaviour unchanged on attempt 1).
    assert load_task_progress(tmp_path, "task-0001") == []
    assert render_prior_progress([]) is None


def test_record_then_load_round_trips(tmp_path: Path) -> None:
    record_task_progress(
        tmp_path,
        "task-0001",
        [_obs("read_file", "Read file: cli.py (lines 690-729 of 2502)"), _obs("search_text", "Found 3 matches")],
    )
    entries = load_task_progress(tmp_path, "task-0001")
    assert entries == [
        "read_file: Read file: cli.py (lines 690-729 of 2502)",
        "search_text: Found 3 matches",
    ]
    block = render_prior_progress(entries)
    assert block is not None
    assert "do" in block.lower() and "NOT redo" in block
    assert "- read_file: Read file: cli.py (lines 690-729 of 2502)" in block


def test_second_attempt_accumulates_and_dedups(tmp_path: Path) -> None:
    record_task_progress(tmp_path, "t", [_obs("read_file", "Read file: a.py")])
    # Re-reading a.py (same summary) must NOT duplicate; a new action appends.
    record_task_progress(
        tmp_path, "t", [_obs("read_file", "Read file: a.py"), _obs("run_command", "pytest ok")]
    )
    entries = load_task_progress(tmp_path, "t")
    assert entries == ["read_file: Read file: a.py", "run_command: pytest ok"]


def test_failed_actions_are_marked(tmp_path: Path) -> None:
    # A failed command must be recorded as failed so the model does not blindly repeat it.
    record_task_progress(tmp_path, "t", [_obs("run_command", "pytest exit 1", ok=False)])
    assert load_task_progress(tmp_path, "t") == ["run_command [failed]: pytest exit 1"]


def test_digest_is_bounded_to_most_recent(tmp_path: Path) -> None:
    record_task_progress(
        tmp_path, "t", [_obs("read_file", f"Read file: f{i}.py") for i in range(_MAX_ENTRIES + 15)]
    )
    entries = load_task_progress(tmp_path, "t")
    assert len(entries) == _MAX_ENTRIES
    # Kept the most-recent window: the last authored action survives, the oldest is dropped.
    assert entries[-1] == f"read_file: Read file: f{_MAX_ENTRIES + 14}.py"
    assert "Read file: f0.py" not in "\n".join(entries)
    block = render_prior_progress(entries)
    assert block is not None and "older actions were trimmed" in block


def test_none_run_dir_is_a_noop(tmp_path: Path) -> None:
    # Runs without a run dir (some smoke paths) must never crash on the digest.
    record_task_progress(None, "t", [_obs("read_file", "Read file: a.py")])
    assert load_task_progress(None, "t") == []


def test_empty_and_blank_observations_write_nothing(tmp_path: Path) -> None:
    record_task_progress(tmp_path, "t", [])
    record_task_progress(tmp_path, "t", [_obs("", ""), _obs("read_file", "")])
    assert load_task_progress(tmp_path, "t") == []
