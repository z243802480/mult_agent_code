from types import SimpleNamespace

from asteria_runtime.core.verification_feedback import boundary_effects, boundary_feedback


def test_feedback_is_bounded_without_hiding_that_paths_were_omitted(tmp_path):
    paths = [f"generated-{i}.bin" for i in range(200)]
    effects = boundary_effects({"edit_boundary": {"mode": "restricted", "paths": ["result.txt"]}}, [
        SimpleNamespace(tool_name="run_command", data={"tool_call_id": "call-source", "workspace_changes": {
            "created": paths, "modified": [], "deleted": [],
        }}),
    ], tmp_path)
    message = boundary_feedback(effects)
    assert len(effects) == 200 and '"omitted_count": 184' in message
    assert "generated-15.bin" in message and "generated-16.bin" not in message
    assert "call-source" in message and "Complete tool observations" in message


def test_unknown_scans_are_not_converted_into_effect_or_resolution_facts(tmp_path):
    unknown = SimpleNamespace(tool_name="run_tests", data={"workspace_changes": None})
    assert boundary_effects({"edit_boundary": {"mode": "restricted", "paths": []}}, [unknown], tmp_path) == []
    assert unknown.data["workspace_changes"] is None
