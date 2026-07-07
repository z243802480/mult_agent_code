import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse
from asteria_runtime.real_model_smoke import P0_MATRIX_CASES, apply_setup_files

from tests.helpers.spine import spine_response
from tests.integration.test_run_command import FakePlanClient, FakeReviewClient

pytestmark = [pytest.mark.workflow, pytest.mark.spine_default]

GATE = json.loads(Path("benchmarks/phase3_rolling_gate.json").read_text(encoding="utf-8"))
CASES_BY_NAME = {case.name: case for case in P0_MATRIX_CASES}


def _doc_update_execute_client(case):
    class Client:
        def chat(self, request: ChatRequest) -> ChatResponse:
            return spine_response(
                request,
                narration="创建文档产物并验证。",
                tool_calls=[
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": case.expected_file,
                            "content": f"# {case.expected_text}\n\n- checklist item\n",
                            "overwrite": True,
                        },
                    },
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": (
                                f"python -c \"from pathlib import Path; "
                                f"text=Path('{case.expected_file}').read_text(encoding='utf-8'); "
                                f"assert '{case.expected_text}' in text\""
                            )
                        },
                    },
                ],
                model_name="fake-doc-execute",
            )

    return Client()


def _bugfix_execute_client():
    class Client:
        def chat(self, request: ChatRequest) -> ChatResponse:
            return spine_response(
                request,
                narration="修复 calc.py 加法 bug 并跑测试。",
                tool_calls=[
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "calc.py",
                            "content": "def add(a, b):\n    return a + b\n",
                            "overwrite": True,
                        },
                    },
                    {
                        "tool_name": "run_command",
                        "args": {"command": "python -m pytest test_calc.py -q"},
                    },
                ],
                model_name="fake-bugfix-execute",
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
