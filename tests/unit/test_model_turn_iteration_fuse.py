"""Budget-aligned task turns preserve a read-heavy conversation (S108)."""
from pathlib import Path

from asteria_runtime.commands import execute_command as ec


def _fuse(tmp_path: Path, policy: dict) -> int:
    return ec.ExecuteCommand(root=tmp_path)._model_turn_iteration_fuse(policy)


def test_default_fuse_uses_the_existing_goal_budget(tmp_path: Path) -> None:
    assert _fuse(tmp_path, {}) == 200
    assert _fuse(tmp_path, {"agent_loop": {}}) == 200
    assert _fuse(tmp_path, {"budgets": {"max_model_calls_per_goal": 7}}) == 7
    assert _fuse(tmp_path, {"budgets": {"max_model_calls_per_goal": 0}}) == 1


def test_retired_fsm_round_setting_does_not_reset_the_conversation(tmp_path: Path) -> None:
    for rounds in [2, 8, 999]:
        assert _fuse(tmp_path, {"agent_loop": {"max_rounds_per_task": rounds}}) == 200


def test_active_budget_profile_is_honored(tmp_path: Path) -> None:
    assert _fuse(tmp_path, {
        "budgets": {"max_model_calls_per_goal": 200},
        "active_budget_profile": "small",
        "budget_profiles": {"small": {"max_model_calls_per_goal": 9}},
    }) == 9


def test_explicit_override_wins(tmp_path: Path) -> None:
    for value, expected in [(3, 3), (40, 40), (0, 1), (-5, 1)]:
        assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": value}}) == expected


def test_malformed_override_falls_back_to_goal_budget(tmp_path: Path) -> None:
    for value in ["lots", None]:
        assert _fuse(tmp_path, {"agent_loop": {"max_turn_iterations": value},
                               "budgets": {"max_model_calls_per_goal": 12}}) == 12


def test_read_then_edit_can_finish_after_sixteen_turns_without_losing_history(tmp_path: Path) -> None:
    from tests.unit.test_model_driven_turn import FakeModelClient, FakeToolResult, FakeToolRunner, _json_resp, _run

    model = FakeModelClient([
        *[_json_resp("inspect", [{"tool_name": "read_file", "args": {"path": f"module_{i}.py"}}]) for i in range(20)],
        _json_resp("implement", [{"tool_name": "write_file", "args": {"path": "answer.py", "content": "answer = 42"}}]),
        _json_resp("done", [], done=True),
    ])
    tools = FakeToolRunner([[FakeToolResult(summary=f"fact-{i}")] for i in range(21)])
    result = _run(model, tools, transport="json", max_iterations=_fuse(tmp_path, {}))
    assert result.status == "completed"
    assert result.iterations == 22
    assert len(result.observations) == 21
    assert tools.calls_seen[-1][0]["tool_name"] == "write_file"
    final_history = "\n".join(message.content for message in model.requests[-1].messages)
    assert "fact-0" in final_history and "fact-19" in final_history
