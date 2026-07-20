from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.orchestration_router import resolve_orchestration_route
from asteria_runtime.core.runtime_orchestration_catalog import (
    WorkspaceOrchestrationState,
    build_runtime_orchestration_catalog,
    load_workspace_orchestration_state,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator

from tests.integration.test_plan_command import FakePlanClient


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_orchestration_catalog_exposes_model_readable_capabilities(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator)
    payload = catalog.to_dict()
    assert payload["capabilities"]
    first = payload["capabilities"][0]
    assert "capability_id" in first
    assert "description" in first
    assert "when_to_use" in first
    assert "layer" in first
    assert "orchestration_paths" not in first


def test_catalog_guidance_cc_spawn_policy(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator)
    guidance = " ".join(catalog.selection_guidance).lower()
    assert "agentloop" in guidance or "subagent" in guidance
    assert "keyword" in guidance or "file count" in guidance
    spawn = catalog.get("spawn_parallel_workers")
    assert spawn is not None
    assert spawn.available is False


def test_warm_workspace_prefers_session_continue_capability(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    plan = PlanCommand(tmp_path, "Add --version", model_client=FakePlanClient()).run()
    run_store = RunStore(tmp_path / ".asteria", validator)
    store = JsonStore(validator)
    run_dir = run_store.run_dir(plan.run_id)
    run = run_store.load_run(plan.run_id)
    run["status"] = "completed"
    run["current_phase"] = "ACCEPTED"
    run_store.update_run(run)
    task_plan = store.read(run_dir / "task_plan.json", "task_board")
    for task in task_plan.get("tasks") or []:
        task["status"] = "done"
    store.write(run_dir / "task_plan.json", task_plan, "task_board")

    state = load_workspace_orchestration_state(tmp_path, validator=validator)
    assert state.session_continue_eligible is True
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator, state=state)
    continue_cap = catalog.get("session_continue_execute")
    assert continue_cap is not None
    assert continue_cap.available is True


def test_ready_for_review_run_opens_new_cold_goal_not_resume(tmp_path: Path) -> None:
    # Regression (warm-session goal-swallowing): a run that finished its loop and is waiting for the
    # human to review must NOT count as in-progress. Otherwise cold_goal_execute is blocked and the
    # model router's only execution path is resume_run — which folds a brand-new goal into the stale
    # run and replays its result. A new top-level goal must be able to start fresh.
    validator = SchemaValidator(SCHEMA_DIR)
    awaiting_review = WorkspaceOrchestrationState(
        initialized=True,
        current_run_id="run-review",
        run_status="running",
        current_phase="EXECUTE",
        workflow_state="ready_for_review",
        session_continue_eligible=False,
        can_review=True,
    )
    catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator, state=awaiting_review)
    cold = catalog.get("cold_goal_execute")
    resume = catalog.get("resume_run")
    assert cold is not None and cold.available is True
    assert resume is not None and resume.available is False

    # Boundary: a genuinely running run that is NOT awaiting review is still resumable, not cold.
    still_running = WorkspaceOrchestrationState(
        initialized=True,
        current_run_id="run-live",
        run_status="running",
        current_phase="EXECUTE",
        workflow_state="executing",
        session_continue_eligible=False,
        can_review=False,
    )
    live_catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator, state=still_running)
    assert live_catalog.get("cold_goal_execute").available is False
    assert live_catalog.get("resume_run").available is True

    # R2-12: the same swallowing, reached the other way — the record still says "running" but the
    # process that wrote it is gone (user Stop tree-killed it; RunStateFinalizer's "more work
    # remains" branch never gets to revise the record). Without liveness this workspace looks busy
    # forever and every later goal is replayed against the dead run.
    zombie = WorkspaceOrchestrationState(
        initialized=True,
        current_run_id="run-zombie",
        run_status="running",
        current_phase="EXECUTE",
        workflow_state="executing",
        session_continue_eligible=False,
        can_review=False,
        writer_process_alive=False,
    )
    zombie_catalog = build_runtime_orchestration_catalog(tmp_path, validator=validator, state=zombie)
    assert zombie_catalog.get("cold_goal_execute").available is True
    assert zombie_catalog.get("resume_run").available is False


class FakeOrchestrationRouterClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=(
                '{"schema_version":"0.1.0","capability_id":"session_continue_execute",'
                '"reason":"Follow-up edit in same workspace.","confidence":"high"}'
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-router",
            raw_response={},
        )


def test_model_orchestration_router_selects_catalog_capability(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    plan = PlanCommand(tmp_path, "Add --version", model_client=FakePlanClient()).run()
    run_store = RunStore(tmp_path / ".asteria", validator)
    store = JsonStore(validator)
    run_dir = run_store.run_dir(plan.run_id)
    run = run_store.load_run(plan.run_id)
    run["status"] = "completed"
    run["current_phase"] = "ACCEPTED"
    run_store.update_run(run)
    task_plan = store.read(run_dir / "task_plan.json", "task_board")
    for task in task_plan.get("tasks") or []:
        task["status"] = "done"
    store.write(run_dir / "task_plan.json", task_plan, "task_board")

    routed = resolve_orchestration_route(
        tmp_path,
        "再给 greet_cli 增加 --quiet 参数",
        validator=validator,
        model_client=FakeOrchestrationRouterClient(),
        router_mode="model",
    )
    assert routed.capability_id == "session_continue_execute"
    assert routed.studio_mode == "continue"
    assert routed.source == "model"


def test_rules_mode_for_maintainer_ci(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)
    routed = resolve_orchestration_route(
        tmp_path,
        "Python 里 list 和 tuple 有什么区别？",
        validator=validator,
        model_client=None,
        router_mode="rules",
    )
    assert routed.capability_id == "chat_answer"
    assert routed.studio_mode == "chat"
    assert routed.source == "rules"


def test_hybrid_policy_alias_routes_via_model(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(SCHEMA_DIR)

    class UnexpectedKeywordPath:
        def chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(
                content=(
                    '{"schema_version":"0.1.0","capability_id":"chat_answer",'
                    '"reason":"Semantic route.","confidence":"high"}'
                ),
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-router",
                raw_response={},
            )

    routed = resolve_orchestration_route(
        tmp_path,
        "Python 里 list 和 tuple 有什么区别？",
        validator=validator,
        model_client=UnexpectedKeywordPath(),
        router_mode="model",
    )
    assert routed.capability_id == "chat_answer"
    assert routed.source == "model"
