"""Consume actual rejection receipts, recheck, revise, and honor the final gate."""
import hashlib
import json
import sys
from dataclasses import replace

import pytest

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_completion_verification_feedback import CHECK, call, response
from tests.integration.test_review_current_artifacts import Reviewer
from tests.integration.test_verification_method_revision import Planner, BAD, CORRECTED
from tests.integration.test_verification_reference_lifecycle import objects


@pytest.mark.parametrize("valid", [True, False])
def test_rejection_facts_support_fresh_revision_without_waiving_checks(tmp_path, valid):
    InitCommand(tmp_path).run()

    class ArtifactPlanner(Planner):
        def chat(self, request):
            result = super().chat(request)
            if request.purpose == "goal_spec":
                goal = json.loads(result.content)
                goal["target_outputs"] = ["src/notes_tool.py"]
                return replace(result, content=json.dumps(goal))
            return result

    plan = PlanCommand(tmp_path, f"create notes and keep exact check {CHECK}",
                       model_client=ArtifactPlanner(), permission_level="auto").run()
    run = tmp_path / ".asteria/runs" / plan.run_id
    original = json.loads((run / "task_plan.json").read_text(encoding="utf8"))["tasks"][0]

    class Model:
        turn = 0
        original_ref = None
        rejected = []

        def chat(self, request):
            self.turn += 1
            payloads = [p for m in request.messages if m.role == "user" for p in objects(m.text())]
            if self.turn == 1:
                seed = json.loads(request.messages[1].text())
                self.original_ref = next(m["verification_ref"] for m in seed["task_contract"]["verification_methods"]
                                         if m["command"] == BAD)
                return response([call("write_file", path="src/notes_tool.py", content="VALUE = 1\n"),
                                 call("run_tests", verification_ref=self.original_ref)])
            if self.turn == 2:
                return response([call("run_tests", command=CORRECTED), call("run_command",
                                 command=f'"{sys.executable}" -c "assert 3 == 3"')])
            if self.turn == 3:
                return response([call("revise_verification", original_command=BAD,
                    replacement_command=CORRECTED, reason="Method raises without checking the artifact",
                    coverage="Preserve the artifact value claim and exact original command")])
            if self.turn == 4:
                facts = [p["verification_rejection"] for p in payloads if "verification_rejection" in p][-1]
                self.rejected.append(facts)
                assert facts["reason_code"] == "replacement_evidence_stale"
                assert facts["invalidating_execution"]["tool_name"] == "run_command"
                assert facts["passed_execution"]["returncode"] == 0
                return response([call("run_tests", command=CORRECTED)])
            if self.turn == 5:
                return response([call("revise_verification", original_verification_ref=self.original_ref,
                    failed_tool_call_id="nonexistent", passed_tool_call_id="nonexistent-too",
                    reason="Fix method", coverage="Keep the same claim")])
            if self.turn == 6:
                facts = [p["verification_rejection"] for p in payloads if "verification_rejection" in p][-1]
                self.rejected.append(facts)
                assert facts["reason_code"] == "execution_reference_unresolved"
                ledger = facts["available_executions"]["observations"]
                failed = [o for o in ledger if o["command_sha256"] == hashlib.sha256(BAD.encode()).hexdigest()][-1]
                passed = [o for o in ledger if o["command_sha256"] == hashlib.sha256(CORRECTED.encode()).hexdigest()][-1]
                return response([call("revise_verification", original_verification_ref=self.original_ref,
                    failed_tool_call_id=failed["tool_call_id"], passed_tool_call_id=passed["tool_call_id"],
                    reason="Method raises without checking the artifact",
                    coverage="Preserve the artifact value claim and exact original command")])
            if self.turn == 7:
                methods = [p["verification_methods"] for p in payloads if "verification_methods" in p][-1]
                required = next(m["verification_ref"] for m in methods if m["command"] == CHECK)
                calls = [] if valid else [call("write_file", path="src/notes_tool.py", content="VALUE = 0\n")]
                return response([*calls, call("run_tests", verification_ref=required)])
            return response()

    model = Model()
    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=model).run()
    assert result.completed == int(valid) and result.blocked == int(not valid)
    assert len(model.rejected) == 2
    task = json.loads((run / "task_plan.json").read_text(encoding="utf8"))["tasks"][0]
    assert task["validation_commands"] == [CORRECTED, CHECK]
    for key in ("acceptance", "completion_contract", "write_scope", "allowed_tools"):
        assert task[key] == original[key]
    rows = [json.loads(s) for s in (run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
    assert len({o["tool_call_id"] for o in rows}) == len(rows)
    assert len([o for o in rows if o["tool_name"] == "revise_verification" and o["ok"]]) == 1
    assert not (run / "decisions.jsonl").exists()
    if valid:
        assert ReviewCommand(tmp_path, plan.run_id, model_client=Reviewer()).run().status == "pass"
        assert AcceptCommand(tmp_path, plan.run_id, skip_review=True).run().accepted
