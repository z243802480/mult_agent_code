"""Directory hints cannot narrow a whole-session read surface or bypass file guards."""

from pathlib import Path

import pytest

from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.execution_preferences import apply_execution_preferences_to_task
from asteria_runtime.core.execution_profile import SESSION_AGENT
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy, ToolPermissionDenied
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.file_tools import ReadFileTool


@pytest.mark.parametrize("text", ["Inspect input/.", "Sphinx/Ruff/mypy/\ncoverage are unavailable."])
def test_unrestricted_scope_stays_unrestricted_when_directory_hints_exist(text):
    task = {"read_scope": [], "write_scope": ["src/change.py"]}
    apply_execution_preferences_to_task(task, {"original_goal": text})
    assert task["read_scope"] == []
    assert task["write_scope"] == ["src/change.py"]


def test_bounded_scope_keeps_its_original_boundary_and_explicit_addition():
    task = {"task_id": "t", "task_kind": "implementation", "read_scope": ["src/"]}
    apply_execution_preferences_to_task(task, {"original_goal": "Inspect input/."})
    assert task["read_scope"] == ["src/", "input/"]
    policy = ToolPermissionPolicy(Path.cwd(), SchemaValidator(Path("schemas")))
    policy.enforce_tool_permission_profile(task, "read_file", {"path": "src/a.py"})
    with pytest.raises(ToolPermissionDenied):
        policy.enforce_tool_permission_profile(task, "read_file", {"path": "unrelated/a.py"})


def test_finalized_model_session_reads_project_context_without_granting_writes(tmp_path):
    goal = {"original_goal": "Update src/change.py. Sphinx/Ruff/mypy/\ncoverage are unavailable.",
            "target_outputs": ["src/change.py"], "expanded_requirements": [],
            "verification_strategy": ["python -m pytest"]}
    tasks = RequirementPlanner().finalize_model_tasks(
        [{"title": "Implement", "description": "Update src/change.py", "task_kind": "implementation",
          "expected_artifacts": ["src/change.py"], "expected_changed_files": ["src/change.py"],
          "acceptance": ["tests pass"]}], goal, execution_profile=SESSION_AGENT)
    task = tasks[0]
    assert task["read_scope"] == []
    policy = ToolPermissionPolicy(tmp_path, SchemaValidator(Path("schemas")))
    policy.enforce_tool_permission_profile(task, "read_file", {"path": "context/spec.md"})
    ctx = RuntimeContext(root=tmp_path, run_id="r", policy={"protected_paths": [".env"]},
                         validator=SchemaValidator(Path("schemas")))
    (tmp_path / ".env").write_text("synthetic fixture", encoding="utf-8")
    with pytest.raises(PermissionError):
        ReadFileTool().run(ctx, ".env")
    with pytest.raises(PermissionError):
        ReadFileTool().run(ctx, "../outside.md")
