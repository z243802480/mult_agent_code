from asteria_runtime.core.agent_tool_surface import (
    adapt_model_tool_call,
    model_tool_surface,
    tool_surface_contract,
)


def test_model_tool_surface_maps_stable_primitives_to_internal_registry() -> None:
    surface = model_tool_surface(
        [
            "read_file",
            "list_files",
            "find_files",
            "search_text",
            "write_file",
            "apply_patch",
            "run_command",
            "run_tests",
        ],
        allow_shell=True,
    )
    tools = {tool["name"]: tool for tool in surface}

    assert tools["glob"]["internal_tool"] == "find_files"
    assert tools["grep"]["internal_tool"] == "search_text"
    assert tools["edit_file"]["internal_tool"] == "apply_patch"
    assert tools["run_tests"]["internal_tool"] == "run_tests"
    assert tools["shell"]["permission"] == "ask"
    assert tools["todo_read"]["status"] == "missing"


def test_tool_surface_contract_separates_internal_and_model_facing_tools() -> None:
    contract = tool_surface_contract(["read_file", "search_text", "apply_patch"])

    assert contract["runtime_internal_registry"]["status"] == "implemented"
    assert contract["model_facing_standard_surface"]["status"] == "partial"
    assert "grep" in contract["model_facing_standard_surface"]["implemented_overlap"]
    assert "list_files" in contract["model_facing_standard_surface"]["missing_primitives"]
    assert "MCP tools are external protocol adapters, not local ToolExecutionGateway tools." in (
        contract["separation_rules"]
    )


def test_tool_surface_contract_is_ready_when_all_model_primitives_have_backends() -> None:
    contract = tool_surface_contract(
        [
            "read_file",
            "list_files",
            "find_files",
            "search_text",
            "write_file",
            "apply_patch",
            "run_command",
            "run_tests",
            "todo_read",
            "todo_write",
        ],
        allow_shell=True,
    )
    tools = {
        tool["name"]: tool
        for tool in contract["model_facing_standard_surface"]["tools"]
    }

    assert contract["model_facing_standard_surface"]["status"] == "ready"
    assert contract["model_facing_standard_surface"]["missing_primitives"] == []
    assert tools["todo_read"]["status"] == "available"
    assert tools["todo_write"]["permission"] == "ask"


def test_adapt_model_tool_call_translates_model_primitive_to_runtime_tool() -> None:
    call = adapt_model_tool_call(
        {"tool_name": "glob", "args": {"pattern": "*.py", "path": "src"}},
        ["find_files"],
    )

    assert call == {
        "tool_name": "find_files",
        "args": {"glob": "*.py", "path": "src"},
        "model_tool_name": "glob",
        "tool_surface_adapter": "model_to_runtime_registry",
    }
