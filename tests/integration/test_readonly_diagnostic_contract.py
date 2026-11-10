import json
from pathlib import Path

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from tests.integration.test_plan_command import FakePlanClient


@pytest.mark.parametrize("mode,expected", [
    ("exploratory_timeout", 1), ("exploratory_denial", 1), ("unread_required", 1),
    ("missing_path", 0), ("protected_path", 0), ("no_read_permission", 0),
    ("empty_readbacks", 0), ("legacy", 0), ("mandatory_failed_command", 0),
])
def test_readonly_diagnostic_contract_uses_real_required_evidence(tmp_path: Path, mode, expected):
    InitCommand(tmp_path).run()
    (tmp_path / "fact.txt").write_text("observed fact", encoding="utf-8")
    (tmp_path / "other.txt").write_text("unrelated evidence", encoding="utf-8")
    plan = PlanCommand(tmp_path, "inspect an existing diagnostic", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria/runs" / plan.run_id
    task_path = run_dir / "task_plan.json"
    board = json.loads(task_path.read_text(encoding="utf-8"))
    required = {"missing_path": "absent.txt", "protected_path": ".env"}.get(mode, "fact.txt")
    task = board["tasks"][0]
    task.update({"task_kind": "diagnostic", "write_scope": [], "expected_changed_files": [],
                 "expected_artifacts": [], "parallel_safety": "readonly",
                 "read_scope": ["AGENTS.md", required, "other.txt"],
                 "allowed_tools": ["read_file", "run_command", "run_tests"],
                 "validation_commands": [],
                 "completion_contract": {"requires_changed_artifact": False,
                                         "requires_verification": True, "allows_expected_failure": False},
                 "verification_policy": {"required": True, "allow_expected_failure": False,
                                         "commands": [], "command_source": "planner_task",
                                         "readback_paths": [] if mode == "empty_readbacks" else [required]}})
    if mode == "legacy":
        task["verification_policy"].pop("readback_paths")
    if mode == "no_read_permission":
        task["allowed_tools"].remove("read_file")
    if mode == "mandatory_failed_command":
        task["validation_commands"] = ['python -c "raise AssertionError(\'required failed\')"']
    task_path.write_text(json.dumps(board), encoding="utf-8")

    class Client:
        calls = 0
        def chat(self, request):
            self.calls += 1
            calls = []
            if self.calls == 1:
                if mode == "exploratory_denial":
                    calls = [{"tool_name": "read_file", "args": {"path": "outside.txt"}}]
                elif mode in {"exploratory_timeout", "legacy"}:
                    calls = [{"tool_name": "run_command", "args": {
                        "command": 'python -c "import time; time.sleep(1)"', "timeout_seconds": 0.01}}]
                else:
                    calls = [{"tool_name": "read_file", "args": {
                        "path": "other.txt" if mode in {"unread_required", "empty_readbacks"} else required}}]
            elif self.calls == 2 and mode in {"exploratory_denial", "exploratory_timeout", "legacy"}:
                calls = [{"tool_name": "read_file", "args": {"path": required}}]
            return ChatResponse(content=json.dumps({"narration": "inspect", "tool_calls": calls, "done": not calls}),
                                finish_reason="stop", usage=TokenUsage(1, 1, 2),
                                model_provider="fake", model_name="evidence-test", raw_response={})

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=Client()).run()
    assert result.completed == expected and result.blocked == 1 - expected
    assert (tmp_path / "fact.txt").read_text(encoding="utf-8") == "observed fact"
    evidence = [json.loads(line) for line in (run_dir / "task_execution_evidence.jsonl").read_text(encoding="utf-8").splitlines()][-1]
    if expected:
        from asteria_runtime.commands.correctness_eval_command import CorrectnessEvalCommand
        assert CorrectnessEvalCommand(tmp_path, plan.run_id).score_signal(run_dir) is None
        assert len(evidence["verification_results"]) == 1
        assert evidence["verification_results"][0]["data"]["path"] == "fact.txt"
    observations = [json.loads(line) for line in (run_dir / "tool_observations.jsonl").read_text(encoding="utf-8").splitlines()]
    if mode in {"exploratory_timeout", "exploratory_denial", "legacy"}:
        assert any(not o["ok"] for o in observations), "exploratory failures must remain in the evidence ledger"
    if mode == "unread_required":
        assert any(o["observation"]["data"].get("path") == "fact.txt" for o in observations)
