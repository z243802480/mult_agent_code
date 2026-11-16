import json
from dataclasses import replace

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_completion_verification_feedback import CHECK, call, response
from tests.integration.test_verification_method_revision import Planner, BAD, CORRECTED
from tests.integration.test_review_current_artifacts import Reviewer


def objects(text):
    decoder = json.JSONDecoder()
    result = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


@pytest.mark.parametrize("valid", [True, False])
def test_execute_reference_failure_revision_updated_index_required_check_review_and_accept(tmp_path, valid):
    InitCommand(tmp_path).run()

    class ReferencePlanner(Planner):
        def chat(self, request):
            result = super().chat(request)
            if request.purpose == "goal_spec":
                goal = json.loads(result.content)
                goal["target_outputs"] = ["src/notes_tool.py"]
                return replace(result, content=json.dumps(goal))
            return result

    plan = PlanCommand(tmp_path, f"create notes and retain this exact check: {CHECK}",
                       model_client=ReferencePlanner(), permission_level="auto").run()
    run = tmp_path / ".asteria/runs" / plan.run_id
    before = json.loads((run / "task_plan.json").read_text(encoding="utf8"))["tasks"][0]

    class Model:
        turn = 0
        original_ref = failed_id = passed_id = None

        def chat(self, request):
            self.turn += 1
            payloads = objects(request.messages[-1].text())
            if self.turn == 1:
                seed = json.loads(request.messages[1].text())
                methods = seed["task_contract"]["verification_methods"]
                self.original_ref = next(m["verification_ref"] for m in methods if m["command"] == BAD)
                return response([call("write_file", path="src/notes_tool.py", content="VALUE = 1\n"),
                                 call("run_tests", verification_ref=self.original_ref)])
            if self.turn == 2:
                self.failed_id = next(p["tool_call_id"] for p in payloads if p.get("verification_ref") == self.original_ref)
                return response([call("run_tests", command=CORRECTED)])
            if self.turn == 3:
                self.passed_id = next(p["tool_call_id"] for p in payloads if p.get("returncode") == 0)
                return response([call("revise_verification", original_verification_ref=self.original_ref,
                    failed_tool_call_id=self.failed_id, passed_tool_call_id=self.passed_id,
                    reason="The registered method raises without checking the produced value",
                    coverage="Check the same value and retain the independently required project command")])
            if self.turn == 4:
                updated = next(p["verification_methods"] for p in payloads if "verification_methods" in p)
                assert self.original_ref not in {m["verification_ref"] for m in updated}
                required = next(m["verification_ref"] for m in updated if m["command"] == CHECK)
                calls = [] if valid else [call("write_file", path="src/notes_tool.py", content="VALUE = 0\n")]
                return response([*calls, call("run_tests", verification_ref=required)])
            return response()

    model = Model()
    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=model).run()
    assert result.completed == int(valid)
    assert result.blocked == int(not valid)
    task = json.loads((run / "task_plan.json").read_text(encoding="utf8"))["tasks"][0]
    revision = task["verification_policy"]["method_revisions"][-1]
    assert revision["reference_binding"] == {"original_verification_ref": model.original_ref,
        "failed_tool_call_id": model.failed_id, "passed_tool_call_id": model.passed_id}
    assert CHECK in task["validation_commands"] and BAD not in task["validation_commands"]
    for key in ("acceptance", "completion_contract", "write_scope", "allowed_tools"):
        assert task[key] == before[key]
    observations = [json.loads(s) for s in (run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
    assert next(o for o in observations if o["tool_call_id"] == model.failed_id)["ok"] is False
    if valid:
        assert ReviewCommand(tmp_path, plan.run_id, model_client=Reviewer()).run().status == "pass"
        assert AcceptCommand(tmp_path, plan.run_id, skip_review=True).run().accepted
