from asteria_runtime.agents.execution_action import normalize_execution_action


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


def test_normalize_execution_action_repairs_missing_html_path_from_expected_artifacts() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {"content": "<!DOCTYPE html><html><body>hi</body></html>"},
            }
        ],
    }
    task = {
        "task_id": "task-web-1",
        "title": "Create static landing page",
        "description": "Build index.html for the landing page",
        "expected_artifacts": ["index.html"],
    }

    normalized = normalize_execution_action(action, task)

    assert normalized["tool_calls"][0]["args"]["path"] == "index.html"
    assert normalized["tool_calls"][0]["args"]["overwrite"] is True


def test_normalize_execution_action_adapts_model_tool_primitives() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "grep",
                "args": {"pattern": "needle", "path": "src"},
                "reason": "inspect source",
            },
            {
                "tool_name": "glob",
                "args": {"pattern": "*.py", "path": "tests"},
            },
        ],
        "verification": [
            {
                "tool_name": "shell",
                "args": {"command": "python -m pytest tests/unit"},
            }
        ],
    }
    task = {
        "task_id": "task-0001",
        "allowed_tools": ["search_text", "find_files", "run_command"],
    }

    normalized = normalize_execution_action(action, task)

    assert normalized["tool_calls"][0]["tool_name"] == "search_text"
    assert normalized["tool_calls"][0]["model_tool_name"] == "grep"
    assert normalized["tool_calls"][1]["tool_name"] == "find_files"
    assert normalized["tool_calls"][1]["args"] == {"glob": "*.py", "path": "tests"}
    assert normalized["verification"][0]["tool_name"] == "run_command"


def test_normalize_execution_action_repairs_json_token_drift_in_python_content() -> None:
    action = {
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {
                    "path": "notes_app/storage.py",
                    "content": (
                        "import \n"
                        "from pathlib import Path\n"
                        "NOTES_FILE = Path(\"notes.json\")\n"
                        "def load_notes():\n"
                        "    return .load(open(NOTES_FILE))\n"
                        "def save_notes(notes):\n"
                        "    .dump(notes, open(NOTES_FILE, 'w'))\n"
                        "try:\n"
                        "    pass\n"
                        "except (.JSONDecodeError, IOError):\n"
                        "    pass\n"
                    ),
                },
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": (
                        "python -c \"import ; data = .load(open('notes.json')); "
                        "assert data == []\""
                    )
                },
            }
        ],
    }
    task = {
        "task_id": "task-0001",
        "title": "Create a notes CLI using notes.json",
        "description": "Persist notes in notes.json",
        "acceptance": ["notes.json stores notes"],
    }

    normalized = normalize_execution_action(action, task)

    content = normalized["tool_calls"][0]["args"]["content"]
    assert "import json\n" in content
    assert "return json.load(" in content
    assert "json.dump(" in content
    assert "except (json.JSONDecodeError" in content
    assert "import json; data = json.load(" in normalized["verification"][0]["args"]["command"]
