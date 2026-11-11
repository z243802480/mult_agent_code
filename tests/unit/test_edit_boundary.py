import json
from pathlib import Path

import pytest

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.candidate_export import CandidateExporter
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.edit_boundary import edit_boundary_allows, validate_edit_boundary
from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_contract import path_in_task_write_scope, write_scope
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.worker_spawn import enrich_child_task
from asteria_runtime.storage.file_backup import FileBackupStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator
from asteria_runtime.tools.backup_tools import RestoreBackupTool
from asteria_runtime.tools.file_tools import WriteFileTool
from asteria_runtime.tools.patch_tools import ApplyPatchTool
from asteria_runtime.tools.registry import ToolRegistry
from tests.unit.test_goal_spec_agent import FakeClient, valid_goal_spec_json


def _boundary(*paths):
    return {"mode": "restricted", "paths": list(paths)}


def _task(boundary):
    return {
        "task_id": "task-0001",
        "task_kind": "implementation",
        "parallel_safety": "serial",
        "allowed_tools": ["write_file", "apply_patch", "restore_backup", "read_file"],
        "read_scope": [],
        "write_scope": ["docs/", "src/", "tests/", "implementation artifact"],
        "edit_boundary": boundary,
    }


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"mode": [], "paths": []},
        {"mode": "restricted", "paths": [42]},
        {"mode": "open", "paths": ["docs/"]},
        {"mode": "restricted", "paths": "docs/"},
        *[
            _boundary(p)
            for p in [
                "",
                ".",
                "./",
                "../x",
                "docs/../x",
                "/tmp/x",
                "C:\\x",
                "\\\\server\\x",
                "a\0b",
            ]
        ],
    ],
)
def test_malformed_boundary_never_grants_edit_access(value):
    with pytest.raises(SchemaValidationError):
        validate_edit_boundary(value)
    if value is not None:
        assert write_scope(_task(value)) == []
        assert not edit_boundary_allows(value, "docs/result.rst")


@pytest.mark.parametrize(
    "path, allowed",
    [
        ("docs/说明 [初稿].rst", True),
        ("notes/deep/item", True),
        ("notes2/item", False),
        ("docs/other.rst", False),
        ("docs/说明 [初稿].rst/child", False),
        ("src/code.py", False),
        ("notes/../src/code.py", False),
        ("/notes/item", False),
    ],
)
def test_literal_file_and_directory_boundaries(path, allowed):
    assert edit_boundary_allows(_boundary("docs/说明 [初稿].rst", "notes/"), path) is allowed


@pytest.mark.parametrize("model_plan", [False, True])
def test_planning_caps_session_surface_and_preserves_persisted_boundary(tmp_path, model_plan):
    payload = json.loads(valid_goal_spec_json())
    payload["target_outputs"] = ["docs/result.rst"]
    payload["normalized_goal"] = "Audit documentation against current implementation"
    payload["expanded_requirements"][0]["description"] = payload["normalized_goal"]
    payload["edit_boundary"] = _boundary("docs/result.rst")
    validator = SchemaValidator(Path("schemas"))
    goal = GoalSpecAgent(FakeClient(json.dumps(payload)), validator).generate(
        "Only edit docs/result.rst; read implementation and tests as needed.", {}, "run-edit"
    )
    planner = RequirementPlanner()
    context = {"workspace_files": [{"path": p} for p in ["docs/result.rst", "src/code.py", "tests/test_code.py"]]}
    if model_plan:
        task = planner.finalize_model_tasks(
            [
                {
                    "task_id": "docs",
                    "description": "Update and verify the requested local documentation",
                    "task_kind": "implementation",
                    "expected_artifacts": ["docs/result.rst"],
                    "expected_changed_files": ["docs/result.rst"],
                }
            ],
            goal,
            context,
            execution_profile="session_agent",
        )[0]
    else:
        task = planner.build_task_plan(
            goal, runtime_context=context, execution_profile="session_agent"
        )["tasks"][0]
    assert task["write_scope"] == ["docs/result.rst"]
    if model_plan:
        assert task["read_scope"] == []
    else:
        original = {key: value for key, value in goal.items() if key != "edit_boundary"}
        before = planner.build_task_plan(
            original, runtime_context=context, execution_profile="session_agent"
        )["tasks"][0]
        assert task["read_scope"] == before["read_scope"]
    task["write_scope"].extend(["src/", "tests/"])
    assert not path_in_task_write_scope("src/code.py", task)
    assert path_in_task_write_scope("docs/result.rst", task)
    store = JsonStore(validator)
    store.write(tmp_path / "task.json", task, "task")
    assert store.read(tmp_path / "task.json", "task")["edit_boundary"] == goal["edit_boundary"]


def test_boundary_is_a_ceiling_not_a_grant_and_open_goals_stay_open():
    task = _task(_boundary("docs/a.rst", "docs/b.rst"))
    task["write_scope"] = ["docs/a.rst"]
    assert write_scope(task) == ["docs/a.rst"]
    assert not path_in_task_write_scope("docs/b.rst", task)
    task["edit_boundary"] = _boundary()
    assert write_scope(task) == []
    for boundary in [None, {"mode": "open", "paths": []}]:
        assert path_in_task_write_scope("src/code.py", _task(boundary))


def _gateway(root):
    validator = SchemaValidator(Path("schemas"))
    context = RuntimeContext(root, "run-edit", {"protected_paths": []}, validator)
    registry = ToolRegistry()
    for tool in [WriteFileTool(), ApplyPatchTool(), RestoreBackupTool()]:
        registry.register(tool)
    return ToolExecutionGateway(registry, ToolPermissionPolicy(root, validator)), context


def test_actual_gateway_denies_multi_file_patch_atomically_and_allows_scoped_write(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "docs/a.rst").write_text("old\n")
    (tmp_path / "src/code.py").write_text("old\n")
    gateway, context = _gateway(tmp_path)
    task = _task(_boundary("docs/a.rst"))
    patch = (
        "--- a/docs/a.rst\n+++ b/docs/a.rst\n@@ -1 +1 @@\n-old\n+new\n"
        "--- a/src/code.py\n+++ b/src/code.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    with pytest.raises(PermissionError, match="edit_boundary"):
        gateway.run_tool_calls(
            [{"tool_name": "apply_patch", "args": {"patch": patch}}], task, context
        )
    assert (
        (tmp_path / "docs/a.rst").read_text() == (tmp_path / "src/code.py").read_text() == "old\n"
    )
    results = gateway.run_tool_calls(
        [{"tool_name": "write_file", "args": {"path": "docs/a.rst", "content": "new\n"}}],
        task,
        context,
    )
    assert results[0].ok and (tmp_path / "docs/a.rst").read_text() == "new\n"
    ToolPermissionPolicy(tmp_path, context.validator).enforce_tool_permission_profile(
        task, "read_file", {"path": "src/code.py"}
    )


def test_restore_checks_every_manifest_target_before_restoring(tmp_path):
    gateway, context = _gateway(tmp_path)
    for name in ["a.rst", "code.py"]:
        (tmp_path / name).write_text("old\n")
    backup = FileBackupStore(context).backup_paths(
        [tmp_path / "a.rst", tmp_path / "code.py"], "test"
    )
    for name in ["a.rst", "code.py"]:
        (tmp_path / name).write_text("new\n")
    with pytest.raises(PermissionError, match="edit_boundary"):
        gateway.run_tool_calls(
            [{"tool_name": "restore_backup", "args": {"backup_id": backup["backup_id"]}}],
            _task(_boundary("a.rst")),
            context,
        )
    assert (tmp_path / "a.rst").read_text() == (tmp_path / "code.py").read_text() == "new\n"


def test_directory_symlink_cannot_redirect_scoped_edits(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    try:
        (tmp_path / "docs/link").symlink_to(tmp_path / "src", target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation unavailable")
    gateway, context = _gateway(tmp_path)
    with pytest.raises(PermissionError, match="edit_boundary"):
        gateway.run_tool_calls(
            [{"tool_name": "write_file", "args": {"path": "docs/link/code.py", "content": "bad"}}],
            _task(_boundary("docs/")),
            context,
        )
    assert not (tmp_path / "src/code.py").exists()


def test_child_scope_and_merge_cannot_override_parent_ceiling(tmp_path):
    parent = _task(_boundary("docs/result.rst"))
    child = enrich_child_task(
        {"write_scope": ["src/", "docs/"], "write_allowed": True}, parent_task=parent
    )
    assert child["edit_boundary"] == parent["edit_boundary"]
    assert write_scope(child) == ["docs/result.rst"]
    assert not MergeGate().evaluate(parent, ["docs/result.rst", "src/code.py"], []).ok


def test_export_reports_out_of_boundary_changes_for_merge_gate(tmp_path):
    source, candidate = tmp_path / "source", tmp_path / "candidate"
    source.mkdir()
    candidate.mkdir()
    (candidate / "docs").mkdir()
    (candidate / "src").mkdir()
    (candidate / "docs/result.rst").write_text("doc")
    (candidate / "src/code.py").write_text("code")
    task = _task(_boundary("docs/result.rst"))
    changes = CandidateExporter(SchemaValidator(Path("schemas"))).discover_changed_files(
        CandidateWorkspace("candidate-1", candidate, source), task=task
    )
    assert changes == ["docs/result.rst", "src/code.py"]
    assert not MergeGate().evaluate(task, changes, []).ok


def test_invalid_goal_proposal_fallback_does_not_grant_writes():
    goal = GoalSpecAgent(FakeClient("not JSON"), SchemaValidator(Path("schemas"))).generate(
        "Original goal", {}, "run-edit"
    )
    plan = RequirementPlanner().build_task_plan(goal, execution_profile="session_agent")
    assert all(write_scope(task) == [] for task in plan["tasks"])


@pytest.mark.parametrize(
    "text, failures",
    [
        ("No executable preview.", 1),
        (
            ">>> class Preview:\n...     def apply_batch(self, ops, *, dry_run):\n...         return 2\n"
            ">>> Preview().apply_batch([], dry_run=True)\n2\n",
            0,
        ),
        (
            ">>> class Preview:\n...     def apply_batch(self, ops, *, dry_run):\n...         return 2\n"
            ">>> Preview().apply_batch([], dry_run=True)\n1\n",
            1,
        ),
    ],
)
def test_dry_run_oracle_executes_expected_outputs(text, failures):
    import runpy

    check = runpy.run_path(str(Path("benchmarks/dogfood/tinydb_doc_dry_run_oracle_s125.py.txt")))
    assert check["verify_dry_run"](text) == failures
