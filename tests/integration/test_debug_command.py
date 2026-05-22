import json
from pathlib import Path

import pytest

from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

pytestmark = pytest.mark.workflow


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a repairable module",
                    "normalized_goal": "Create a repairable module",
                    "goal_type": "software_tool",
                    "assumptions": ["local python module"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Create a module exposing VALUE = 2",
                            "source": "inferred",
                            "acceptance": ["VALUE equals 2"],
                        }
                    ],
                    "target_outputs": ["repairable.py"],
                    "definition_of_done": ["VALUE equals 2"],
                    "verification_strategy": ["python command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeBrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create module with wrong value.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "repairable.py",
                                "content": "VALUE = 1\n",
                                "overwrite": True,
                            },
                            "reason": "create initial implementation",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                            },
                            "reason": "verify expected value",
                        }
                    ],
                    "completion_notes": "intentionally broken",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        failure_evidence = payload["failure_evidence"]
        assert "prompt_envelope" in payload["runtime_context"]
        assert "capability_manifest" in payload["runtime_context"]["prompt_envelope"]
        assert payload["runtime_context"]["tool_observations"]
        assert "runtime_os_evidence" in failure_evidence
        assert "recent_worker_results" in failure_evidence
        assert "recent_merge_gate_evidence" in failure_evidence
        assert "recent_runtime_requests" in failure_evidence
        assert "recent_tool_failures" in request.messages[-1].content
        assert "recent_task_failures" in request.messages[-1].content
        assert "recent_task_execution_evidence" in request.messages[-1].content
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Fix VALUE to satisfy verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "repairable.py",
                                "content": "VALUE = 2\n",
                                "overwrite": True,
                            },
                            "reason": "minimal repair",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                            },
                            "reason": "verify repaired value",
                        }
                    ],
                    "completion_notes": "repairable.py now exposes VALUE = 2",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


class FakePatchDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        assert (
            '"tool_name": "apply_patch"'
            in request.messages[0].content + request.messages[-1].content
        )
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Patch VALUE to satisfy verification.",
                    "tool_calls": [
                        {
                            "tool_name": "apply_patch",
                            "args": {
                                "patch": "--- a/repairable.py\n+++ b/repairable.py\n@@\n-VALUE = 0\n+VALUE = 2\n"
                            },
                            "reason": "minimal patch repair",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                            },
                            "reason": "verify repaired value",
                        }
                    ],
                    "completion_notes": "repairable.py patched to VALUE = 2",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


class FakeStillBrokenDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Attempt a repair that still fails verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "repairable.py",
                                "content": "VALUE = 3\n",
                                "overwrite": True,
                            },
                            "reason": "incorrect repair",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                            },
                            "reason": "verify repaired value",
                        }
                    ],
                    "completion_notes": "still broken",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


class FakeVerifyOnlyDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Verify the artifact is already correct.",
                    "tool_calls": [],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                            },
                            "reason": "prove task is already satisfied",
                        }
                    ],
                    "completion_notes": "repairable.py already exposes VALUE = 2",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


def test_debug_command_repairs_blocked_task_and_updates_costs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()
    ).run()
    assert execute.blocked == 1

    result = DebugCommand(tmp_path, run_id=plan.run_id, model_client=FakeDebugClient()).run()

    assert result.repaired == 1
    assert result.still_blocked == 0
    assert (tmp_path / "repairable.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    debug_envelope = json.loads(
        (run_dir / "prompt_envelope_debug.json").read_text(encoding="utf-8")
    )
    assert debug_envelope["mode"] == "debug"
    assert "failure_repair" in debug_envelope["section_order"]
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "done"
    assert "VALUE = 2" in task_plan["tasks"][0]["notes"]

    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "repair_started" in events
    assert "repair_completed" in events
    task_failures = [
        json.loads(line)
        for line in (run_dir / "task_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert task_failures[0]["failure_type"] == "contract_violation"
    assert task_failures[0]["verification_failures"][0]["error"] == "nonzero_exit"
    execution_evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [item["status"] for item in execution_evidence] == ["blocked", "done"]
    assert execution_evidence[-1]["candidate"]["promoted_files"] == ["repairable.py"]
    assert execution_evidence[-1]["verification_results"][0]["ok"] is True

    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 3
    assert cost_report["tool_calls"] == 5
    assert cost_report["repair_attempts"] == 1
    assert cost_report["estimated_input_tokens"] == 37
    assert cost_report["estimated_output_tokens"] == 63


def test_debug_command_records_repair_user_progress(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()
    ).run()
    assert execute.blocked == 1

    DebugCommand(tmp_path, run_id=plan.run_id, model_client=FakeDebugClient()).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    titles = [event["title"] for event in progress]
    assert "Repair started" in titles
    assert "Repair evidence loaded" in titles
    assert "Repair action requested" in titles
    assert "Repair action proposed" in titles
    assert "Repair candidate workspace created" in titles
    assert "Repair verification started" in titles
    assert "Repair contract checked" in titles
    assert "Repair candidate promoted" in titles
    assert "Repair evidence recorded" in titles
    assert any(
        event["channel"] == "file" and event["file_changes"]
        for event in progress
    )
    assert any(
        event["channel"] == "evidence"
        and event["phase"] == "result"
        and event["title"] == "Repair evidence recorded"
        for event in progress
    )


def test_debug_command_can_repair_with_apply_patch(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    (tmp_path / "repairable.py").write_text("VALUE = 0\n", encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()
    ).run()
    assert execute.blocked == 1
    assert (tmp_path / "repairable.py").read_text(encoding="utf-8") == "VALUE = 0\n"

    result = DebugCommand(tmp_path, run_id=plan.run_id, model_client=FakePatchDebugClient()).run()

    assert result.repaired == 1
    assert (tmp_path / "repairable.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    tool_calls = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert "apply_patch" in tool_calls


def test_debug_command_discards_failed_repair_candidate(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()
    ).run()
    assert execute.blocked == 1

    result = DebugCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeStillBrokenDebugClient()
    ).run()

    assert result.repaired == 0
    assert result.still_blocked == 1
    assert not (tmp_path / "repairable.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[-1]["decision"] == "discard"
    assert experiments[-1]["candidate"]["workspace"]
    assert (Path(experiments[-1]["candidate"]["workspace"]) / "repairable.py").exists()
    assert experiments[-1]["candidate"]["rollback"] == []
    assert experiments[-1]["candidate"]["promoted_files"] == []
    task_failures = [
        json.loads(line)
        for line in (run_dir / "task_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert task_failures[-1]["failure_type"] == "repair_contract_violation"
    assert task_failures[-1]["contract_check"]["violations"] == ["verification did not pass"]
    execution_evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert execution_evidence[-1]["status"] == "blocked"
    assert execution_evidence[-1]["failure_type"] == "repair_contract_violation"
    assert execution_evidence[-1]["candidate"]["promoted_files"] == []


def test_debug_command_can_mark_already_satisfied_task_done(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    task_plan["tasks"][0]["status"] = "blocked"
    task_plan["tasks"][0]["notes"] = (
        "Verification command failed, but artifact may already be correct."
    )
    (run_dir / "task_plan.json").write_text(json.dumps(task_plan), encoding="utf-8")
    (tmp_path / "repairable.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = DebugCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeVerifyOnlyDebugClient()
    ).run()

    assert result.repaired == 1
    updated = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert updated["tasks"][0]["status"] == "done"
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[-1]["decision"] == "keep"
    assert "already satisfied" in experiments[-1]["reason"]
