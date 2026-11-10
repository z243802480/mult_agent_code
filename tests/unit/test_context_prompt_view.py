from copy import deepcopy

from asteria_runtime.core.context_prompt_view import context_prompt_view, execution_prompt_view


def test_execution_view_references_duplicate_guidance_without_mutating_runtime() -> None:
    context = {
        "prompt_envelope": {
            "path": "run/prompt_envelope_execute.json",
            "content_hash": "sha256:example",
            "sections": [
                {"name": "safety_envelope", "summary": "Network is denied"},
                {"name": "user_communication", "summary": "Hard-stop at budget 0.90"},
                {"name": "custom_section", "summary": "Keep custom instructions"},
            ],
            "capability_manifest": {"boundaries": {"network": "deny"}},
            "extension": {"instruction": "keep unknown fields"},
        },
        "root_guidance": {"path": "AGENTS.md", "content": "Project rule", "truncated": True},
        "context_package": {
            "root_guidance": {"path": "AGENTS.md", "content": "Project rule\nMore rules"},
            "context_envelope": {"payload": {"duplicate": "content"}, "payload_hash": "abc"},
            "context_envelope_path": "run/context.json",
            "recent_failures": [{"error": "actual failed check"}],
        },
        "model_tool_surface": {"tools": [{"parameter_contract": {"required": ["path"]}}]},
        "task_contract": {"write_scope": ["calc.py"], "acceptance": ["tests pass"]},
        "permissions": {"allow_shell": False},
        "budget": {"max_calls": 3},
        "custom_extension": {"instructions": "do not lose this"},
    }
    original = deepcopy(context)

    view = execution_prompt_view(context, project_guidance="Project rule\nMore rules")

    assert context == original
    # A persisted reference alone does not prove that audit text is redundant.
    assert view["prompt_envelope"] == original["prompt_envelope"]
    for guidance in (view["root_guidance"], view["context_package"]["root_guidance"]):
        assert "content" not in guidance
        assert guidance["content_ref"] == "system.project_guidance"
    for key in ("model_tool_surface", "task_contract", "permissions", "budget", "custom_extension"):
        assert view[key] == original[key]
    assert view["context_package"]["recent_failures"] == original["context_package"]["recent_failures"]
    assert view["context_package"]["context_envelope"]["payload_ref"] == "run/context.json"
    # Other callers retain the generic view, including their audit/guidance fields.
    assert context_prompt_view(context)["root_guidance"]["content"] == "Project rule"


def test_unreferenced_envelope_and_uncovered_guidance_are_preserved() -> None:
    for context in (
        {"prompt_envelope": {"sections": ["custom instructions"]}},
        {"root_guidance": {"path": "AGENTS.md", "content": "Rules plus an unseen tail"}},
        {"root_guidance": {"path": "OTHER.md", "content": "Rules"}},
        {"root_guidance": {"path": "AGENTS.md", "content": "Changed rules"}},
        {"root_guidance": "legacy instructions"},
    ):
        assert execution_prompt_view(context, project_guidance="Rules") == context


def test_absent_system_guidance_does_not_remove_project_instructions() -> None:
    context = {"context_package": {"root_guidance": {"path": "AGENTS.md", "content": "Rules"}}}
    assert execution_prompt_view(context) == context
