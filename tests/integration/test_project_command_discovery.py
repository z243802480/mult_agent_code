"""Project metadata must not invent executable checks or overwrite user choices."""
import hashlib
import json

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.review_evidence import ReviewEvidence
from asteria_runtime.core.verification_revision import method_provenance
from tests.unit.test_review_tools import setup


def project(root):
    InitCommand(root).run()
    return json.loads((root / ".asteria/project.json").read_text(encoding="utf8"))


def test_python_metadata_does_not_invent_a_test_runner_or_src_layout(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "stdlib-project"\n', encoding="utf8")
    (tmp_path / "AGENTS.md").write_text("Tests: python -m unittest discover -s checks\n", encoding="utf8")
    config = project(tmp_path)
    assert all(value is None for value in config["commands"].values())
    assert config["command_sources"] == {}
    authority = method_provenance(["pytest"], {}, {
        "root_guidance": {"content": (tmp_path / "AGENTS.md").read_text(), "truncated": False},
        "project_commands": config["commands"],
    })
    assert authority["revisable_commands"] == ["pytest"]


def test_actual_tool_configuration_has_precise_sources_and_no_invented_src(tmp_path):
    content = b'[tool.pytest.ini_options]\ntestpaths = ["checks"]\n[tool.ruff]\nline-length = 90\n[tool.mypy]\nfiles = ["flat.py"]\n'
    (tmp_path / "pyproject.toml").write_bytes(content)
    config = project(tmp_path)
    assert config["commands"]["test"] == "pytest"
    assert config["commands"]["lint"] == "ruff check ."
    assert config["commands"]["typecheck"] == "mypy"
    source = config["command_sources"]["test"]
    assert source == {"path": "pyproject.toml", "selector": "tool.pytest.ini_options",
                      "content_sha256": hashlib.sha256(content).hexdigest(), "basis": "tool_configuration"}


def test_mypy_configuration_without_targets_does_not_invent_them(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.mypy]\nstrict = true\n', encoding="utf8")
    assert project(tmp_path)["commands"]["typecheck"] is None


def test_package_scripts_are_discovered_only_when_declared_without_executing_them(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": "node checks.mjs", "lint": "node lint.mjs", "format": "echo formatting",
        "install": "echo never execute", "dev": "", "build": 3}}), encoding="utf8")
    config = project(tmp_path)
    assert config["commands"] == {"install": "npm install", "test": "npm test", "lint": "npm run lint",
                                  "format": "npm run format", "run": None, "build": None, "typecheck": None}
    assert config["command_sources"]["test"]["selector"] == "scripts.test"
    assert config["command_sources"]["test"]["basis"] == "package_script"
    assert not (tmp_path / "node_modules").exists()


def test_mixed_project_does_not_let_unconfigured_python_hide_a_declared_package_test(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "mixed"\n', encoding="utf8")
    (tmp_path / "package.json").write_text('{"scripts":{"test":"node check.mjs"}}', encoding="utf8")
    assert project(tmp_path)["commands"]["test"] == "npm test"


@pytest.mark.parametrize("content", ["{}", '{"scripts":[]}', "{broken", '[]'])
def test_missing_or_invalid_scripts_never_become_npm_test_or_dev(tmp_path, content):
    (tmp_path / "package.json").write_text(content, encoding="utf8")
    config = project(tmp_path)
    assert config["commands"]["test"] is config["commands"]["run"] is config["commands"]["build"] is None


@pytest.mark.parametrize("content", [b"[broken", b"\xff", b" " * 262_145], ids=["invalid", "encoding", "oversized"])
def test_unreadable_or_oversized_configuration_is_not_guessed(tmp_path, content):
    (tmp_path / "pyproject.toml").write_bytes(content)
    assert all(v is None for v in project(tmp_path)["commands"].values())


def test_linked_config_is_not_read_or_attributed_to_the_workspace(tmp_path):
    external = tmp_path.parent / (tmp_path.name + "-external.toml")
    external.write_text("[tool.pytest.ini_options]\n", encoding="utf8")
    try:
        (tmp_path / "pyproject.toml").symlink_to(external)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert project(tmp_path)["commands"]["test"] is None


def test_reinit_preserves_existing_user_commands_and_guidance_byte_for_byte(tmp_path):
    project(tmp_path)
    path = tmp_path / ".asteria/project.json"
    config = json.loads(path.read_text())
    config["commands"]["test"] = "python -m unittest discover -s checks"
    config.pop("command_sources", None)  # Existing schema-valid projects need no migration.
    path.write_text(json.dumps(config), encoding="utf8")
    before = path.read_bytes(), (tmp_path / "AGENTS.md").read_bytes()
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf8")
    project(tmp_path)
    assert before == (path.read_bytes(), (tmp_path / "AGENTS.md").read_bytes())


def test_review_keeps_command_sources_inline_without_certifying_coverage(tmp_path):
    tools = setup(tmp_path)
    source = {"path": "package.json", "selector": "scripts.test", "content_sha256": "a" * 64,
              "basis": "package_script"}
    context = {"project": {"commands": {"test": "npm test"}, "command_sources": {"test": source}}}
    evidence = ReviewEvidence(tools.context, tools.artifacts["evidence_id"], tools.task["task_id"],
                              context, [], [], {"tasks": []})
    assert evidence.input_view()["project"] == context["project"]
    assert evidence.input_view()["review_evidence"]["verification_methods"]["requirement_coverage"] == "unassessed"
    tools.finish("completed")


def test_planner_receives_command_sources_as_data(tmp_path):
    from asteria_runtime.agents.plan_agent import PlanAgent
    from asteria_runtime.storage.schema_validator import SchemaValidator
    source = {"path": "package.json", "selector": "scripts.test", "content_sha256": "a" * 64,
              "basis": "package_script"}
    prompt = PlanAgent(None, SchemaValidator(tmp_path / "missing"))._user_prompt(
        {}, {"project_commands": {"test": "npm test"}, "project_command_sources": {"test": source}}, "default",
    )
    assert '"discovered_sources_at_init"' in prompt and '"selector": "scripts.test"' in prompt


def test_persisted_source_metadata_is_schema_validated(tmp_path):
    from asteria_runtime.storage.schema_validator import SchemaValidator, SchemaValidationError
    config = project(tmp_path)
    config["command_sources"] = {"test": {"path": 42, "selector": "", "content_sha256": "", "basis": "invented"}}
    with pytest.raises(SchemaValidationError):
        SchemaValidator(tmp_path / "missing").validate("project_config", config)
