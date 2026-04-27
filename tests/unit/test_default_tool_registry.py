from agent_runtime.tools.defaults import create_default_tool_registry


def test_default_tool_registry_contains_mvp_tools() -> None:
    registry = create_default_tool_registry()

    assert registry.names() == [
        "apply_patch",
        "diff_workspace",
        "find_files",
        "list_files",
        "read_file",
        "run_command",
        "run_tests",
        "search_text",
        "write_file",
    ]
