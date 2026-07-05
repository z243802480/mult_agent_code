"""S-Skill-1/2/3: real skill handler (loads body), gateway routing, model surface filter."""
from pathlib import Path

from asteria_runtime.core.agent_tool_surface import skill_model_tools
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.skill_adapter import SkillAdapter, SkillBodyHandler, SkillManifestHandler
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator

SKILL_MD = """---
name: greet
description: Greet the user politely
---

# Procedure

1. Say hello.
2. Summarize what was done.
"""


def _skill_root(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "skills" / "greet"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / "helper.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path / "skills"


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=SchemaValidator(Path.cwd() / "schemas"),
        run_dir_override=tmp_path,
    )


def test_body_handler_loads_full_procedure_not_just_frontmatter(tmp_path: Path) -> None:
    root = _skill_root(tmp_path)
    adapter = SkillAdapter.from_skill_roots([root], handler="body")
    assert isinstance(adapter.handlers["greet"], SkillBodyHandler)
    out = adapter.handlers["greet"].invoke({"arguments": {}})
    assert "# Procedure" in out["data"]["instructions"]
    assert "Say hello" in out["data"]["instructions"]
    assert "helper.py" in out["data"]["bundled_files"]
    # contrast: the default discovery-only handler returns no body
    manifest = SkillAdapter.from_skill_roots([root])  # default = manifest
    assert isinstance(manifest.handlers["greet"], SkillManifestHandler)
    assert "instructions" not in manifest.handlers["greet"].invoke({})["data"]


def test_discover_skills_and_surface_filter(tmp_path: Path) -> None:
    adapter = SkillAdapter.from_skill_roots([_skill_root(tmp_path)], handler="body")
    discovered = adapter.discover_skills()
    assert any(d["model_name"] == "skill__greet" for d in discovered)
    # empty allowed_skills => all allowed
    assert all(t["task_allowed"] for t in skill_model_tools(discovered, {}))
    # named contract
    tools = {t["name"]: t for t in skill_model_tools(discovered, {"allowed_skills": ["other"]})}
    assert tools["skill__greet"]["task_allowed"] is False
    assert tools["skill__greet"]["permission"] == "deny"


def test_gateway_routes_skill_to_adapter(tmp_path: Path) -> None:
    adapter = SkillAdapter.from_skill_roots([_skill_root(tmp_path)], handler="body")
    context = _context(tmp_path)
    gateway = ToolExecutionGateway(registry=None, permission_policy=None, skill_adapter=adapter)
    task = {
        "task_id": "t1",
        "task_kind": "implementation",
        "allowed_tools": [],
        "allowed_skills": ["greet"],
    }
    results = gateway.run_tool_calls(
        [{"tool_name": "skill__greet", "args": {}}], task, context, stop_on_failure=False
    )
    assert len(results) == 1 and results[0].ok is True
    observation = getattr(results[0], "harness_observation", None)
    assert observation is not None and observation.ok and observation.tool_name == "skill__greet"
    assert "Procedure" in results[0].data["instructions"]
    invocations = JsonlStore(context.validator).read_all(
        tmp_path / "skill_invocations.jsonl", "skill_invocation"
    )
    assert len(invocations) == 1 and invocations[0]["skill_name"] == "greet"


def test_bundled_default_skills_are_real_and_body_loadable() -> None:
    # The shipped default skills (skills/bundled, wired first by ExecuteCommand._wire_skill_adapter)
    # must be genuine procedures: discovered by name, non-empty description, and body-loadable via the
    # SAME handler the live execute path uses (handler="body") — not empty stubs.
    import asteria_runtime

    bundled = Path(asteria_runtime.__file__).resolve().parent / "skills" / "bundled"
    adapter = SkillAdapter.from_skill_roots([bundled], handler="body")
    names = {d["name"] for d in adapter.discover_skills()}
    assert {"verify", "investigate", "debug", "minimal-change"} <= names
    for name, handler in adapter.handlers.items():
        assert isinstance(handler, SkillBodyHandler), name
        out = handler.invoke({"arguments": {}})
        instructions = out["data"]["instructions"]
        assert "## Steps" in instructions, name  # a real procedure, not echoed frontmatter
        assert out["data"]["skill_definition"]["description"].strip(), name


def test_gateway_skill_denied_outside_contract(tmp_path: Path) -> None:
    adapter = SkillAdapter.from_skill_roots([_skill_root(tmp_path)], handler="body")
    context = _context(tmp_path)
    gateway = ToolExecutionGateway(registry=None, permission_policy=None, skill_adapter=adapter)
    task = {
        "task_id": "t1",
        "task_kind": "implementation",
        "allowed_tools": [],
        "allowed_skills": ["other"],
    }
    results = gateway.run_tool_calls(
        [{"tool_name": "skill__greet", "args": {}}], task, context, stop_on_failure=False
    )
    assert results[0].ok is False
    assert results[0].status == "denied"
