"""Per-task turn fuse for the model-driven spine (ADR-0016): a runaway backstop, not a cognitive
round ceiling.

Regression guard for dogfood residual② (run-20260718): the fuse used to be
``max_rounds_per_task(≤8) + 4`` (default 6), inherited from the retired FSM's per-task *round*
concept. That was too tight for a read-heavy edit — the model read a handful of files to understand
the code, tripped the fuse before writing, got replanned, and re-read everything from scratch. The
fuse is a boundary (goal budget + loop guard are the real governors), so the default is now generous
and explicitly overridable.
"""
from pathlib import Path

from asteria_runtime.commands import execute_command as ec


def _fuse(tmp_path: Path, policy: dict) -> int:
    return ec.ExecuteCommand(root=tmp_path)._model_turn_iteration_fuse(policy)


def test_default_fuse_is_generous_headroom(tmp_path: Path) -> None:
    # No agent_loop config at all → generous default (16), not the old FSM-derived 6.
    assert _fuse(tmp_path, {}) == 16
    assert _fuse(tmp_path, {"agent_loop": {}}) == 16
    # A modest max_rounds_per_task still floors at the generous default (read-then-edit needs room).
    assert _fuse(tmp_path, {"agent_loop": {"max_rounds_per_task": 2}}) == 16


def test_high_max_rounds_widens_beyond_floor(tmp_path: Path) -> None:
    # max_rounds_per_task is capped at 8 by _agent_loop_max_rounds → 8 + 4 = 12, still < 16 floor.
    assert _fuse(tmp_path, {"agent_loop": {"max_rounds_per_task": 8}}) == 16
    # ...and an absurd value is clamped before it can inflate the fuse.
    assert _fuse(tmp_path, {"agent_loop": {"max_rounds_per_task": 999}}) == 16


def test_explicit_override_wins(tmp_path: Path) -> None:
    # Tests / prod can force a specific fuse via the explicit knob (quick fuse or wider).
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": 3}}) == 3
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": 40}}) == 40
    # Override floors at 1 — never zero/negative (that would trip the fuse before any model call).
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": 0}}) == 1
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": -5}}) == 1


def test_malformed_override_falls_back_to_default(tmp_path: Path) -> None:
    # A non-integer override is ignored, not crashed on → generous default.
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": "lots"}}) == 16
    assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": None}}) == 16
