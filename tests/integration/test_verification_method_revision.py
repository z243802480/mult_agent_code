"""Plan -> real tools -> explicit method revision -> actual Execute completion gate."""

import json
import sys
from dataclasses import replace

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from tests.integration.test_completion_verification_feedback import CHECK, call, response
from tests.integration.test_execute_command import FakePlanClient


BAD = f'"{sys.executable}" -c "raise RuntimeError(\'planner method defect\')"'
CORRECTED = CHECK.replace("import Path;", "import Path as P;").replace("Path('src/", "P('src/")


class Planner(FakePlanClient):
    def chat(self, request):
        answer = super().chat(request)
        if request.purpose == "task_planning":
            self.planning_prompt = request.messages[-1].content
            content = json.dumps({"tasks": [{
                "title": "Create the scoped notes artifact", "description": "Produce VALUE = 1",
                "task_kind": "implementation", "acceptance": ["Original artifact check passes"],
                "expected_artifacts": ["src/notes_tool.py"],
                "expected_changed_files": ["src/notes_tool.py"],
                "validation_commands": [BAD, CHECK],
            }]})
        else:
            goal = json.loads(answer.content)
            goal["verification_strategy"] = [CHECK]
            content = json.dumps(goal)
        return replace(answer, content=content)


class Implementer:
    def __init__(self, adopt, valid):
        self.turn = 0
        self.adopt = adopt
        self.valid = valid

    def chat(self, request):
        self.turn += 1
        if self.turn == 1:
            return response([call("write_file", path="src/notes_tool.py", content="VALUE = 1\n"),
                             call("run_tests", command=BAD)])
        if self.turn == 2:
            return response([call("run_tests", command=CORRECTED)])
        if self.turn == 3 and self.adopt:
            return response([call("revise_verification", original_command=BAD,
                replacement_command=CORRECTED,
                reason="Planner's method raised before inspecting the artifact",
                coverage="Check the exact artifact value, preserving the separate original command")])
        if self.turn == 4 and not self.valid:
            return response([call("write_file", path="src/notes_tool.py", content="VALUE = 0\n")])
        return response()


@pytest.mark.parametrize("adopt,valid,long_guidance", [
    (False, True, False), (True, True, False), (True, False, False), (True, True, True),
])
def test_revision_is_explicit_and_preserves_required_checks_and_freshness(tmp_path, adopt, valid, long_guidance):
    guidance = "Keep requested requirements and original checks.\n"
    (tmp_path / "AGENTS.md").write_text(guidance * (100 if long_guidance else 1)
                                      + ("AUTHORITY_TAIL_ONLY" if long_guidance else ""), encoding="utf8")
    InitCommand(tmp_path).run()
    planner = Planner()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=planner).run()
    assert "verification_authority" not in planner.planning_prompt
    assert "AUTHORITY_TAIL_ONLY" not in planner.planning_prompt
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    board_path = run_dir / "task_plan.json"
    original = json.loads(board_path.read_text(encoding="utf8"))["tasks"][0]
    assert original["verification_policy"]["method_provenance"]["revisable_commands"] == [BAD]
    result = ExecuteCommand(tmp_path, run_id=plan.run_id,
                            model_client=Implementer(adopt, valid)).run()
    assert result.completed == int(adopt and valid)
    assert result.blocked == int(not (adopt and valid))
    task = json.loads(board_path.read_text(encoding="utf8"))["tasks"][0]
    assert task["acceptance"] == original["acceptance"]
    assert task["completion_contract"] == original["completion_contract"]
    assert CHECK in task["validation_commands"]
    assert (BAD not in task["validation_commands"]) == adopt
    rows = [json.loads(line) for line in (run_dir / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
    failed = [r for r in rows if r["observation"].get("data", {}).get("requested_command", r["observation"].get("data", {}).get("command")) == BAD]
    assert failed and not failed[0]["ok"]
    evidence = [json.loads(line) for line in (run_dir / "task_execution_evidence.jsonl").read_text(encoding="utf8").splitlines()]
    assert (not evidence[-1]["contract_check"]["violations"]) == (adopt and valid)
