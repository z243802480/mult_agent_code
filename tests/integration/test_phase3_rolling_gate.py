import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.real_model_smoke import P0_MATRIX_CASES, apply_setup_files

from tests.integration.test_run_command import FakePlanClient, FakeReviewClient

pytestmark = pytest.mark.workflow

GATE = json.loads(Path("benchmarks/phase3_rolling_gate.json").read_text(encoding="utf-8"))
CASES_BY_NAME = {case.name: case for case in P0_MATRIX_CASES}


def _doc_update_execute_client(case):
    class Client:
        def chat(self, request: ChatRequest) -> ChatResponse:
            task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
            return ChatResponse(
                content=json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "task_id": task_id,
                        "summary": "Create documentation artifact.",
                        "tool_calls": [
                            {
                                "tool_name": "write_file",
                                "args": {
                                    "path": case.expected_file,
                                    "content": f"# {case.expected_text}\n\n- checklist item\n",
                                    "overwrite": True,
                                },
                                "reason": "create doc artifact",
                            }
                        ],
                        "verification": [
                            {
                                "tool_name": "run_command",
                                "args": {
                                    "command": (
                                        f"python -c \"from pathlib import Path; "
                                        f"text=Path('{case.expected_file}').read_text(encoding='utf-8'); "
                                        f"assert '{case.expected_text}' in text\""
                                    )
                                },
                                "reason": "verify doc artifact",
                            }
                        ],
                        "completion_notes": "doc created",
                    }
                ),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-doc-execute",
                raw_response={},
            )

    return Client()


def _bugfix_execute_client():
    class Client:
        def chat(self, request: ChatRequest) -> ChatResponse:
            task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
            return ChatResponse(
                content=json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "task_id": task_id,
                        "summary": "Fix calc.py addition bug.",
                        "tool_calls": [
                            {
                                "tool_name": "write_file",
                                "args": {
                                    "path": "calc.py",
                                    "content": "def add(a, b):\n    return a + b\n",
                                    "overwrite": True,
                                },
                                "reason": "fix bug",
                            }
                        ],
                        "verification": [
                            {
                                "tool_name": "run_command",
                                "args": {"command": "python -m pytest test_calc.py -q"},
                                "reason": "run tests",
                            }
                        ],
                        "completion_notes": "calc fixed",
                    }
                ),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-bugfix-execute",
                raw_response={},
            )

    return Client()


@pytest.mark.parametrize("case_id", [item["id"] for item in GATE["required_cases"][:2]])
def test_phase3_rolling_gate_fake_scoped_case(tmp_path: Path, case_id: str) -> None:
    case = CASES_BY_NAME[case_id]
    apply_setup_files(tmp_path, case.setup_files)
    InitCommand(tmp_path).run()
    execute_client = (
        _doc_update_execute_client(case)
        if case_id == "doc_update"
        else _bugfix_execute_client()
    )
    result = RunCommand(
        tmp_path,
        case.goal,
        plan_model_client=FakePlanClient(),
        execute_model_client=execute_client,
        review_model_client=FakeReviewClient(),
        enable_research=False,
        max_iterations=3,
        max_tasks_per_iteration=1,
    ).run()

    assert result.status == "completed"
    expected = tmp_path / case.expected_file
    assert expected.exists()
    assert case.expected_text in expected.read_text(encoding="utf-8")
