"""Subagent continuation policy — CC/Codex-aligned parent loop stop after child success."""

from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator


def _minimal_context(tmp_path: Path) -> RuntimeContext:
    validator = SchemaValidator(Path.cwd() / "schemas")
    template = json.loads(
        (Path.cwd() / "src" / "asteria_runtime" / "templates" / "policies.default.json").read_text(
            encoding="utf-8"
        )
    )
    return RuntimeContext(
        root=tmp_path,
        run_id="run-test",
        policy=template,
        validator=validator,
        budget=BudgetController(template, run_id="run-test"),
    )


def test_parent_loop_stops_after_successful_subagent(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    cmd = ExecuteCommand(tmp_path)
    context = _minimal_context(tmp_path)
    observation = {"status": "succeeded", "next_recommended_action": "stop"}
    assert (
        cmd._should_continue_after_subagent(
            context=context,
            round_index=1,
            max_rounds=8,
            observation=observation,
        )
        is False
    )


def test_parent_loop_continues_after_failed_subagent_for_repair(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    cmd = ExecuteCommand(tmp_path)
    context = _minimal_context(tmp_path)
    observation = {"status": "failed", "next_recommended_action": "repair"}
    assert (
        cmd._should_continue_after_subagent(
            context=context,
            round_index=1,
            max_rounds=8,
            observation=observation,
        )
        is True
    )


def test_parent_loop_does_not_continue_on_stop_without_success(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    cmd = ExecuteCommand(tmp_path)
    context = _minimal_context(tmp_path)
    observation = {"status": "failed", "next_recommended_action": "stop"}
    assert (
        cmd._should_continue_after_subagent(
            context=context,
            round_index=1,
            max_rounds=8,
            observation=observation,
        )
        is False
    )


def test_agent_loop_continues_after_failed_attempt_when_observation_requests_repair(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    cmd = ExecuteCommand(tmp_path)
    context = _minimal_context(tmp_path)
    observation = {"status": "failed", "next_recommended_action": "repair"}
    assert (
        cmd._should_continue_agent_loop(
            context=context,
            round_index=1,
            max_rounds=2,
            observation=observation,
            next_action={"expected_observation": {}},
            attempt_status="blocked",
        )
        is True
    )


def test_agent_loop_does_not_continue_when_original_decision_lacks_follow_up_on_success(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    cmd = ExecuteCommand(tmp_path)
    context = _minimal_context(tmp_path)
    observation = {"status": "succeeded", "next_recommended_action": None}
    assert (
        cmd._should_continue_agent_loop(
            context=context,
            round_index=1,
            max_rounds=2,
            observation=observation,
            next_action={"expected_observation": {}},
            attempt_status="done",
        )
        is False
    )
