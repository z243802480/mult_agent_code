import json
from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.replan_command import ReplanCommand
import pytest

from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from tests.helpers.spine import spine_response

# RA7b slice 3: replan drives the 立真身 spine (production default) — opt out of the legacy-FSM pin.
pytestmark = pytest.mark.spine_default


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
                            "description": "Create a module exposing answer()",
                            "source": "inferred",
                            "acceptance": ["answer() returns 42"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["answer() returns 42"],
                    "verification_strategy": ["python command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeBrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="创建模块（值写错）并验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "complete_module.py",
                        "content": "def answer():\n    return 41\n",
                        "overwrite": True,
                    },
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            'python -c "from complete_module import answer; assert answer() == 42"'
                        )
                    },
                },
            ],
            model_name="fake-execute",
        )


def test_replan_command_creates_repair_task_from_task_failure_evidence(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    result = ReplanCommand(tmp_path, run_id=plan.run_id).run()

    assert result.created_tasks == 1
    assert result.created_decisions == 0
    assert result.superseded_tasks == ["task-0001"]
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert [task["status"] for task in task_plan["tasks"]] == ["discarded", "ready"]
    repair_task = task_plan["tasks"][1]
    assert repair_task["task_id"] == "task-0002"
    # F5: the plan-panel title is Chinese and NEVER carries the raw task-000x bookkeeping id (the
    # surface layer neutralizes those). It distinguishes repairs by the source task's own title.
    assert repair_task["title"].startswith(("修复", "为「", "修改"))
    assert "task-000" not in repair_task["title"]
    assert not repair_task["title"].startswith(("Add ", "Repair ", "Modify "))
    assert repair_task["replan"]["source_evidence_id"] == "task-execution-0001"
    assert repair_task["expected_changed_files"] == ["complete_module.py"]
    assert "list_files" in repair_task["allowed_tools"]
    assert "Primary evidence: task-execution-0001" in repair_task["description"]
    # 直写脊梁没有候选工作区(FSM 候选隔离已随重塑退役),故修复描述不再引用 "Candidate workspace:"。
    assert "verification did not pass" in repair_task["description"]
    backlog = json.loads(
        (tmp_path / ".asteria" / "tasks" / "backlog.json").read_text(encoding="utf-8")
    )
    assert backlog["tasks"][1]["task_id"] == "task-0002"
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["title"] == "准备重规划" for event in user_progress)
    assert any(
        event["title"] == "已创建修复任务" and event["data"]["new_task_id"] == "task-0002"
        for event in user_progress
    )
    assert any(event["title"] == "重规划完成" for event in user_progress)


def test_replan_command_creates_decision_after_replan_limit(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    result = ReplanCommand(
        tmp_path,
        run_id=plan.run_id,
        max_replans_per_task=0,
    ).run()

    assert result.created_tasks == 0
    assert result.created_decisions == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "replan_decision"
    assert decisions[0]["metadata"]["source_evidence_id"] == "task-execution-0001"
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decision_events = [event for event in user_progress if event["event_type"] == "decision"]
    assert any(event["data"]["decision"]["reason"] == "repair_limit" for event in decision_events)


def test_replan_command_enforces_lineage_limit_on_chained_repairs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()
    first = ReplanCommand(tmp_path, run_id=plan.run_id, max_replans_per_task=2).run()
    assert first.created_tasks == 1

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()
    second = ReplanCommand(tmp_path, run_id=plan.run_id, max_replans_per_task=2).run()
    assert second.created_tasks == 1

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()
    third = ReplanCommand(tmp_path, run_id=plan.run_id, max_replans_per_task=2).run()
    assert third.created_tasks == 0
    assert third.created_decisions == 1


def test_repair_task_inherits_source_scopes_so_brief_gate_passes(tmp_path: Path) -> None:
    # Dogfood run-20260718 #3: a repair task with no write_scope of its own AND empty
    # expected_changed_files (the pre-existing-test strip can empty it) has an empty
    # "allowed_writes" brief field, and the delegation brief quality gate hard-denies the
    # worker before the model runs. The repair continues the source task's work inside the
    # same boundary — it must inherit the source scopes.
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0]["write_scope"] = ["notes/", "implementation artifact"]
    task_plan["tasks"][0]["read_scope"] = []
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    ReplanCommand(tmp_path, run_id=plan.run_id).run()

    repaired = json.loads(task_plan_path.read_text(encoding="utf-8"))["tasks"][1]
    assert repaired["write_scope"] == ["notes/", "implementation artifact"]
    assert repaired["read_scope"] == []

    from asteria_runtime.core.worker_recorder import WorkerExecutionRecorder

    gate = WorkerExecutionRecorder(run_dir).delegation_gate(repaired)
    assert gate["status"] == "pass", gate["reason"]


class FakeCorrectButUnverifiedExecuteClient:
    """Writes a CORRECT artifact but never runs the declared validation command.

    Reproduces the real-stack finding (validation_small_cli, 2026-07-22): the doer sometimes
    declares itself done right after writing, without ever running its own verification command.
    The completion contract correctly blocks this (its only violation is the missing check, not a
    wrong artifact) — but the repair that follows must be allowed to close by re-verifying alone.
    """

    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="创建模块（未验证）。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "complete_module.py",
                        "content": "def answer():\n    return 42\n",
                        "overwrite": True,
                    },
                },
            ],
            model_name="fake-execute-unverified",
        )


class FakeVerifyOnlyExecuteClient:
    """Re-runs ONLY the validation command — no write — as a correct repair should when the prior
    attempt's artifact was already right and only unverified."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="重新验证已有实现。",
            tool_calls=[
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            'python -c "from complete_module import answer; assert answer() == 42"'
                        )
                    },
                },
            ],
            model_name="fake-execute-verify-only",
        )


def test_verified_noop_repair_closes_when_source_only_lacked_verification(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeCorrectButUnverifiedExecuteClient()
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert evidence[0]["contract_check"]["violations"] == ["required verification was not provided"]

    result = ReplanCommand(tmp_path, run_id=plan.run_id).run()
    assert result.created_tasks == 1
    repair_task = json.loads(task_plan_path.read_text(encoding="utf-8"))["tasks"][1]
    # The source task's ONLY violation was "never verified" — the write was already correct — so
    # this repair may close by re-verifying alone, without touching the file again.
    assert repair_task["verified_noop_allowed"] is True

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeVerifyOnlyExecuteClient()).run()
    repaired_status = json.loads(task_plan_path.read_text(encoding="utf-8"))["tasks"][1]["status"]
    assert repaired_status == "done"


def test_verified_noop_not_allowed_when_source_verification_actually_failed(
    tmp_path: Path,
) -> None:
    # Guardrail: verified_noop_allowed must stay False whenever the source task's violations
    # include anything beyond "never verified" (e.g. a genuinely wrong artifact) — reopening it
    # for "verification did not pass" would recreate the ring_val_f gaming hole this stays narrow
    # to avoid.
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    ReplanCommand(tmp_path, run_id=plan.run_id).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    repair_task = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))["tasks"][1]
    assert repair_task["verified_noop_allowed"] is False
