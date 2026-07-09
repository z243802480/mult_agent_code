import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand, _looks_like_test_path
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

pytestmark = pytest.mark.workflow


def test_looks_like_test_path() -> None:
    assert _looks_like_test_path("test_foo.py")
    assert _looks_like_test_path("foo_test.py")
    assert _looks_like_test_path("conftest.py")
    assert _looks_like_test_path("tests/unit/test_x.py")
    assert _looks_like_test_path("pkg/test/thing.py")
    assert not _looks_like_test_path("foo.py")
    assert not _looks_like_test_path("src/mystery.py")
    assert not _looks_like_test_path("contest.py")


def test_protect_verification_specs_strips_preexisting_test_from_impl_scope(tmp_path: Path) -> None:
    """Anti-tamper (ring_val_e): a pre-existing test file (the spec) is removed from an implementation
    task's write_scope + expected_changed_files so the model can't rewrite the test it's judged by;
    a NOT-yet-existing test stays writable (legitimate authoring); non-impl tasks are untouched."""
    (tmp_path / "test_mystery.py").write_text("assert False\n", encoding="utf-8")
    cmd = PlanCommand(tmp_path, "make test_mystery.py pass")
    task_plan = {
        "tasks": [
            {
                "task_id": "task-0001",
                "task_kind": "implementation",
                "write_scope": ["mystery.py", "test_mystery.py"],
                "expected_changed_files": ["mystery.py", "test_mystery.py"],
            },
            {
                "task_id": "task-0002",
                "task_kind": "implementation",
                "write_scope": ["feature.py", "test_new_feature.py"],
                "expected_changed_files": ["test_new_feature.py"],
            },
            {
                "task_id": "task-0003",
                "task_kind": "verification",
                "write_scope": ["test_mystery.py"],
                "expected_changed_files": ["test_mystery.py"],
            },
        ]
    }

    cmd._protect_verification_specs(task_plan)
    t1, t2, t3 = task_plan["tasks"]

    assert t1["write_scope"] == ["mystery.py"]
    assert t1["expected_changed_files"] == ["mystery.py"]
    # a NEW test (not yet on disk) stays writable — legitimate test authoring is unaffected
    assert "test_new_feature.py" in t2["write_scope"]
    assert t2["expected_changed_files"] == ["test_new_feature.py"]
    # a non-implementation task is left alone
    assert t3["write_scope"] == ["test_mystery.py"]


class FakePlanClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "做一个密码测试工具",
                    "normalized_goal": "构建本地优先密码测试工具",
                    "goal_type": "software_tool",
                    "assumptions": ["用户希望本地运行"],
                    "constraints": ["local_first", "privacy_safe"],
                    "non_goals": ["不证明密码绝对安全"],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "提供密码强度评分",
                            "source": "inferred",
                            "acceptance": ["输入密码后显示评分"],
                        },
                        {
                            "id": "req-0002",
                            "priority": "should",
                            "description": "提供隐私说明",
                            "source": "inferred",
                            "acceptance": ["说明密码不会发送到外部服务"],
                        },
                    ],
                    "target_outputs": ["local_cli", "readme", "tests"],
                    "definition_of_done": ["可以运行", "有测试"],
                    "verification_strategy": ["unit_tests"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


class FailingPlanClient:
    provider = "fake"

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        assert request.purpose == "goal_spec"
        raise RuntimeError("HTTP 429 rate limit")


class TransientPlanClient(FakePlanClient):
    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.requests:
            self.requests.append(request)
            raise RuntimeError("stream deadline exceeded")
        return super().chat(request)


def test_plan_command_creates_run_goal_spec_tasks_and_logs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    assert result.task_count == 1
    assert result.goal_spec_path.exists()
    assert result.task_plan_path.exists()
    assert result.task_plan_eval_path.exists()
    assert result.cost_report_path.exists()
    assert result.task_plan_status in {"pass", "warn"}

    task_plan = json.loads(result.task_plan_path.read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 1
    assert task_plan["tasks"][0]["status"] == "ready"
    assert task_plan["tasks"][0]["agent_loop_profile"]["loop_profile_id"] in {
        "default",
        "multi_agent",
        "research",
        "brainstorm",
        "session_agent",
    }
    assert task_plan["tasks"][0]["agent_loop_profile"]["output_contract"]
    task_plan_eval = json.loads(result.task_plan_eval_path.read_text(encoding="utf-8"))
    assert task_plan_eval["run_id"] == result.run_id
    assert task_plan_eval["task_count"] == 1
    assert task_plan_eval["overall_score"] == result.task_plan_score
    assert "Task plan quality" in result.to_text()

    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    prompt_envelope = json.loads((run_dir / "prompt_envelope.json").read_text(encoding="utf-8"))
    assert {
        "identity",
        "project_guidance",
        "capability_manifest",
        "failure_repair",
        "delegation_contract",
        "user_communication",
    }.issubset(set(prompt_envelope["section_order"]))
    assert prompt_envelope["capability_manifest"]["direct_tools"]
    assert prompt_envelope["capability_manifest"]["verification"]
    loop_dispatch = json.loads((run_dir / "agent_loop_dispatch.json").read_text(encoding="utf-8"))
    assert loop_dispatch["task_dispatch"][0]["task_id"] == "task-0001"
    assert loop_dispatch["task_dispatch"][0]["capability_invocation_policy"]["reason"]
    assert loop_dispatch["task_dispatch"][0]["validation_contract"]
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) >= 4
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["phase"] for event in user_progress[:2]] == ["understand", "plan"]
    plan_events = [
        event
        for event in user_progress
        if event.get("transcript_kind") == "plan" and event.get("display_level") == "main"
    ]
    assert plan_events
    assert plan_events[-1]["phase"] == "plan"
    assert plan_events[-1]["title"] == "计划已生成"
    assert user_progress[-1]["phase"] == "next"
    channels = {event["channel"] for event in user_progress}
    assert {"conclusion", "progress", "tool", "file", "evidence"}.issubset(channels)
    assert any(
        event["channel"] == "tool" and event["event_type"] == "tool_call"
        for event in user_progress
    )
    assert any(
        event["channel"] == "file" and event["file_changes"]
        for event in user_progress
    )
    assert any(
        event["title"] == "Agent loop profiles selected"
        and event["data"]["agent_loop_dispatch"]["task_dispatch"]
        for event in user_progress
    )
    assert all(event["display_level"] in {"main", "inspector"} for event in user_progress)
    assert user_progress[1]["call_chain"] == ["PlanCommand", "AgentHarness"]
    assert any(
        event["call_chain"] == ["PlanCommand", "GoalSpecAgent"]
        for event in user_progress
    )
    assert any(
        event["data"].get("capability_manifest")
        for event in user_progress
        if event["call_chain"] == ["PlanCommand", "AgentHarness"]
    )
    assert any(
        event["data"].get("prompt_envelope", {}).get("sections")
        for event in user_progress
        if event["call_chain"] == ["PlanCommand", "AgentHarness"]
    )
    assert plan_events[-1]["artifact_refs"]

    backlog = json.loads(
        (tmp_path / ".asteria" / "tasks" / "backlog.json").read_text(encoding="utf-8")
    )
    assert len(backlog["tasks"]) == 1


def test_plan_command_records_model_failure_report_and_failed_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    client = FailingPlanClient()

    with pytest.raises(RuntimeError, match="rate_limited"):
        PlanCommand(tmp_path, "build a local-first helper", model_client=client).run()

    assert len(client.requests) == 2

    report_path = tmp_path / ".asteria" / "model" / "latest_failure.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["provider"] == "fake"
    assert report["failure_type"] == "rate_limited"

    memories = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "memory" / "failures.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert memories[0]["source"]["kind"] == "model_failure_report"
    assert memories[0]["source"]["failure_type"] == "rate_limited"

    run_dirs = sorted((tmp_path / ".asteria" / "runs").iterdir(), key=lambda item: item.name)
    run = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert run["current_phase"] == "SPEC"
    assert "Failure report:" in run["summary"]


def test_plan_command_retries_transient_goal_spec_timeout(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    client = TransientPlanClient()

    result = PlanCommand(tmp_path, "build a local-first helper", model_client=client).run()

    assert result.task_count == 1
    assert [request.model_tier for request in client.requests] == ["medium", "medium"]
    run_dirs = sorted((tmp_path / ".asteria" / "runs").iterdir(), key=lambda item: item.name)
    events = [
        json.loads(line)
        for line in (run_dirs[-1] / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["type"] == "model_route_retry" for event in events)
    assert any(event["type"] == "model_route_retry_succeeded" for event in events)


def test_plan_command_downgrades_low_risk_goal_spec_route_from_strategy(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    _write_blocked_goal_spec_profile(tmp_path)
    client = FakePlanClient()

    PlanCommand(
        tmp_path,
        "Update README documentation for local setup.",
        model_client=client,
    ).run()

    assert client.requests[0].model_tier == "medium"
    run_dirs = sorted((tmp_path / ".asteria" / "runs").iterdir(), key=lambda item: item.name)
    events = [
        json.loads(line)
        for line in (run_dirs[-1] / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    route_event = next(event for event in events if event["type"] == "model_route_selected")
    assert route_event["data"]["selected_model_tier"] == "medium"
    assert "downgrade_low_risk_goal_spec_to_medium" in route_event["data"]["actions"]


def _write_blocked_goal_spec_profile(root: Path) -> None:
    model_dir = root / ".asteria" / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "capability_profile.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "root": str(root),
                "profile_count": 1,
                "profiles": [
                    {
                        "provider": "zai",
                        "model": "glm-4.7",
                        "purpose": "goal_spec",
                        "model_tier": "strong",
                        "total_calls": 5,
                        "success_calls": 3,
                        "failure_calls": 2,
                        "success_rate": 0.6,
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_workers": 0,
                        "successful_workers": 0,
                        "failed_workers": 0,
                        "worker_success_rate": 0.0,
                        "validation_total": 0,
                        "validation_passed": 0,
                        "validation_pass_rate": 0.0,
                        "runtime_request_total": 0,
                        "runtime_request_rate": 0.0,
                        "runtime_request_types": {},
                        "merge_gate_blocks": 0,
                        "failure_types": {"timeout": 1},
                        "recent_failures": ["stream deadline exceeded"],
                        "recommended_action": "keep_route",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
