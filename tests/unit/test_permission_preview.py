from asteria_runtime.core.permission_preview import permission_preview_for_runtime_requests


def test_permission_preview_exposes_exact_read_and_write_scope() -> None:
    preview = permission_preview_for_runtime_requests(
        [
            {
                "request_type": "scope_expansion",
                "risk": "medium",
                "details": {
                    "read_scope": ["src/current.py"],
                    "write_scope": ["src/new.py", "tests/test_new.py"],
                },
            }
        ]
    )

    assert preview["action"] == "Allow additional workspace changes"
    assert preview["scope"] == "Read: src/current.py; Write: src/new.py, tests/test_new.py"
    assert preview["network"] == "No additional network access requested."
    assert preview["scope_detail"]["read_scope"] == ["src/current.py"]
    assert preview["scope_detail"]["write_scope"] == ["src/new.py", "tests/test_new.py"]


def test_permission_preview_marks_external_tool_network_boundary() -> None:
    preview = permission_preview_for_runtime_requests(
        [
            {
                "request_type": "tool_request",
                "risk": "high",
                "details": {"allowed_tools": ["external_mcp"]},
            }
        ]
    )

    assert preview["scope"] == "Tools: external_mcp"
    assert preview["network"] == "The requested tool may access an external service."
    assert preview["risk"] == "high"
