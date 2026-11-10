from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.core.execution_environment import command_execution_context


def test_execution_prompt_exposes_repository_fact_and_diff_contract(tmp_path: Path) -> None:
    import json

    _, user = ExecuteCommand(tmp_path)._model_driven_prompts(
        task={}, goal_spec={}, project_config={}, available_tools=["diff_workspace"],
        runtime_context={},
    )
    payload = json.loads(user)
    assert payload["execution_environment"]["git_repository_detected"] is False
    function = payload["tool_contracts"][0]["function"]
    assert function["name"] == "diff_workspace"
    assert function["parameters"]["required"] == ["path", "original"]


def test_nested_worktree_is_detected_without_reading_git_metadata(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("unread metadata", encoding="utf-8")
    child = tmp_path / "src"
    child.mkdir()
    assert command_execution_context(child)["git_repository_detected"] is True
