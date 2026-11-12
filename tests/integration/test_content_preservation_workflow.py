from dataclasses import replace
import json
import sys

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.replan_command import ReplanCommand
from tests.integration.test_completion_verification_feedback import call, response
from tests.integration.test_execute_command import FakePlanClient

CHECK = f'"{sys.executable}" -c "from pathlib import Path; assert Path(\'note.txt\').exists()"'


class Planner(FakePlanClient):
    def chat(self, request):
        answer = super().chat(request)
        if request.purpose == "task_planning":
            content = {
                "tasks": [
                    {
                        "title": "Add a new section without changing existing lines",
                        "description": "Add a section to note.txt",
                        "task_kind": "implementation",
                        "acceptance": ["Original lines preserved and new section exists"],
                        "expected_artifacts": ["note.txt"],
                        "expected_changed_files": ["note.txt"],
                        "validation_commands": [CHECK],
                    }
                ]
            }
        else:
            content = json.loads(answer.content)
            content["content_preservation"] = [{"path": "note.txt", "mode": "existing_lines"}]
            content["verification_strategy"] = [CHECK]
        return replace(answer, content=json.dumps(content))


class Writer:
    def __init__(self, content):
        self.content = content
        self.turn = 0

    def chat(self, request):
        self.turn += 1
        return (
            response([call("write_file", path="note.txt", content=self.content)])
            if self.turn == 1
            else response()
        )


@pytest.mark.parametrize("damage", [False, True])
def test_plan_capture_execute_gate_and_replan_keep_original_baseline(tmp_path, damage):
    (tmp_path / "AGENTS.md").write_text(
        "Keep existing lines when adding a new section.\n", encoding="utf8"
    )
    # The file tool writes the supplied UTF-8 bytes; seed matching endings on both hosts.
    original = "first\nsecond\n"
    (tmp_path / "note.txt").write_bytes(original.encode("utf8"))
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "Add a section, preserving every existing line in note.txt",
        model_client=Planner(),
    ).run()
    run = tmp_path / ".asteria" / "runs" / plan.run_id
    snapshot = (run / "content_preservation.json").read_bytes()
    content = "first # changed\nsecond\nnew section\n" if damage else "first\nnew section\nsecond\n"
    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=Writer(content)).run()
    assert result.completed == int(not damage)
    assert result.blocked == int(damage)
    evidence = [
        json.loads(line)
        for line in (run / "task_execution_evidence.jsonl").read_text(encoding="utf8").splitlines()
    ]
    assert evidence[-1]["contract_check"]["ok"] == (not damage)
    assert evidence[-1]["contract_check"]["verification_passed"] > 0
    if damage:
        assert any("existing lines" in v for v in evidence[-1]["contract_check"]["violations"])
        ReplanCommand(tmp_path, run_id=plan.run_id).run()
        repaired = ExecuteCommand(
            tmp_path, run_id=plan.run_id, model_client=Writer("first\nnew section\nsecond\n")
        ).run()
        assert repaired.completed == 1
    assert (run / "content_preservation.json").read_bytes() == snapshot
