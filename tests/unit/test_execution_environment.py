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


def test_execution_prompt_keeps_guidance_in_system_and_contract_in_payload(tmp_path: Path) -> None:
    import json

    guidance = "Verify the original tests and never read secrets."
    task = {"write_scope": ["calc.py"], "acceptance": ["test_calc.py passes"]}
    context = {
        "root_guidance": {"path": "AGENTS.md", "content": guidance},
        "prompt_envelope": {
            "path": "run/prompt.json", "content_hash": "abc", "sections": ["audit"],
        },
    }
    system, user = ExecuteCommand(tmp_path)._model_driven_prompts(
        task=task, goal_spec={}, project_config={}, available_tools=["diff_workspace"],
        runtime_context=context, project_guidance=guidance,
    )
    payload = json.loads(user)
    assert guidance in system
    assert "content" not in payload["runtime_context"]["root_guidance"]
    assert payload["task_contract"]["write_scope"] == ["calc.py"]
    assert payload["task_contract"]["acceptance"] == ["test_calc.py passes"]
    assert payload["tool_contracts"][0]["function"]["parameters"]["required"] == ["path", "original"]
    assert context["root_guidance"]["content"] == guidance
