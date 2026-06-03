import base64
import json
from pathlib import Path

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator


def _policy() -> dict:
    return {
        "budgets": {
            "max_model_calls_per_goal": 5,
            "max_tool_calls_per_goal": 10,
            "max_total_minutes_per_goal": 30,
            "max_iterations_per_goal": 8,
            "max_repair_attempts_total": 2,
            "max_repair_attempts_per_task": 1,
            "max_replans_per_task": 1,
            "max_research_calls": 1,
            "max_user_decisions": 1,
        },
        "context": {
            "model_context_window_tokens": 100,
            "compaction_threshold": 0.75,
            "hard_stop_threshold": 0.9,
        },
    }


def test_fake_model_returns_goal_spec_json() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[
                ChatMessage(role="user", content="User goal:\nmake a thing\n\nProject context:\n{}")
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["goal_id"] == "goal-0001"
    assert payload["original_goal"] == "make a thing"
    assert payload["expanded_requirements"][0]["description"]
    assert response.model_provider == "fake"


def test_fake_model_goal_spec_tracks_requested_file_contract() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="medium",
            messages=[
                ChatMessage(
                    role="user",
                    content=(
                        "User goal:\nCreate a local file p0_matrix_file_output.txt "
                        "containing one line: P0 matrix file output ok\n\n"
                        "Project context:\n{}"
                    ),
                )
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["target_outputs"] == ["p0_matrix_file_output.txt"]
    requirement = payload["expanded_requirements"][0]
    assert requirement["expected_artifacts"] == ["p0_matrix_file_output.txt"]
    assert "P0 matrix file output ok" in payload["definition_of_done"][1]


def test_fake_model_returns_execution_action_for_task() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="task_execution",
            model_tier="medium",
            messages=[
                ChatMessage(
                    role="user",
                    content=json.dumps({"task": {"task_id": "task-0001"}}),
                )
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["task_id"] == "task-0001"
    assert payload["tool_calls"][0]["tool_name"] == "write_file"


def test_fake_model_execution_action_writes_requested_content() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="task_execution",
            model_tier="medium",
            messages=[
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "task": {
                                "task_id": "task-0001",
                                "description": (
                                    "Create or update p0_matrix_file_output.txt with "
                                    "deterministic fake-model content."
                                ),
                                "expected_changed_files": ["p0_matrix_file_output.txt"],
                                "acceptance": [
                                    "p0_matrix_file_output.txt exists",
                                    "p0_matrix_file_output.txt contains 'P0 matrix file output ok'",
                                    "local verification passes",
                                ],
                            }
                        }
                    ),
                )
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    call = payload["tool_calls"][0]
    assert call["args"]["path"] == "p0_matrix_file_output.txt"
    assert call["args"]["content"] == "P0 matrix file output ok\n"
    expected = base64.b64encode(b"P0 matrix file output ok").decode("ascii")
    assert expected in payload["verification"][0]["args"]["command"]


def test_fake_model_execution_action_handles_simple_python_repairs() -> None:
    response = FakeModelClient().chat(
        ChatRequest(
            purpose="task_execution",
            model_tier="medium",
            messages=[
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "task": {
                                "task_id": "task-0001",
                                "description": "Fix calc.py so add(2, 3) returns 5.",
                                "expected_changed_files": ["calc.py"],
                                "acceptance": ["add(2, 3) returns 5"],
                            }
                        }
                    ),
                )
            ],
            response_format="json",
        )
    )

    payload = json.loads(response.content)

    assert payload["tool_calls"][0]["args"]["path"] == "calc.py"
    assert "return a + b" in payload["tool_calls"][0]["args"]["content"]


def test_fake_model_records_context_window_estimate() -> None:
    budget = BudgetController(_policy(), run_id="run-1")
    client = FakeModelClient(budget=budget)

    client.chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[ChatMessage(role="user", content="x" * 240)],
            response_format="json",
        )
    )

    report = budget.cost_report()
    assert report["latest_context_estimated_tokens"] > 0
    assert report["context_window_tokens"] == 100
    assert report["context_pressure_status"] in {"within_budget", "near_limit"}


def test_fake_model_records_runtime_user_progress(tmp_path: Path) -> None:
    client = FakeModelClient(logger=ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))))

    client.chat(
        ChatRequest(
            purpose="goal_spec",
            model_tier="strong",
            messages=[
                ChatMessage(role="user", content="User goal:\nmake a thing\n\nProject context:\n{}")
            ],
            response_format="json",
            metadata={
                "run_id": "run-1",
                "agent_id": "GoalSpecAgent",
                "agent_role_contract": {
                    "role": "GoalSpecAgent",
                    "purpose": "goal_spec",
                    "deadline_profile": "strong_goal_spec",
                    "provider_call_seconds": 42,
                    "stream_idle_timeout_seconds": 7,
                    "max_model_calls": 1,
                },
                "context_mode": "slim",
                "fast_path_task_kind": "simple_file",
            },
        )
    )

    events = [
        json.loads(line)
        for line in (tmp_path / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(event["channel"], event["event_type"]) for event in events] == [
        ("model", "start"),
        ("model", "delta"),
        ("model", "end"),
    ]
    assert events[0]["phase"] == "plan"
    assert events[0]["telemetry"]["role"] == "GoalSpecAgent"
    assert events[0]["telemetry"]["deadline_ms"] == 42000
    logged = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8"))
    assert logged["agent_role"] == "GoalSpecAgent"
    assert logged["deadline_profile"] == "strong_goal_spec"
    assert logged["deadline_ms"] == 42000
    assert logged["context_mode"] == "slim"
    assert logged["fast_path_task_kind"] == "simple_file"
