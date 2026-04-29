from agent_runtime.agents.execution_action import normalize_execution_action


def test_normalize_execution_action_fills_required_context_fields() -> None:
    action = {
        "summary": "verify file",
        "tool_calls": [
            {
                "name": "read_file",
                "arguments": {"path": "hello_runtime.txt"},
                "reason": "check content",
            }
        ],
    }

    normalized = normalize_execution_action(action, {"task_id": "task-0002"})

    assert normalized["schema_version"] == "0.1.0"
    assert normalized["task_id"] == "task-0002"
    assert normalized["tool_calls"] == [
        {
            "tool_name": "read_file",
            "args": {"path": "hello_runtime.txt"},
            "reason": "check content",
        }
    ]
    assert normalized["verification"] == []


def test_normalize_execution_action_repairs_obvious_write_file_args() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"content": "real model smoke ok"},
            }
        ],
    }
    task = {
        "task_id": "task-0001",
        "title": "Create file named 'hello_runtime.txt'",
        "description": "Create file named hello_runtime.txt",
        "acceptance": ["File contains 'real model smoke ok'"],
    }

    normalized = normalize_execution_action(action, task)

    assert normalized["tool_calls"][0]["args"] == {
        "path": "hello_runtime.txt",
        "content": "real model smoke ok",
        "overwrite": True,
    }
