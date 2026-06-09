from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.validation_run_command import ValidationRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunResult, RunStepSummary
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def _assert_validation_run_result_control_surface(payload: dict) -> None:
    contract = payload["control_surface"]

    assert payload["schema_version"] == "0.1.0"
    assert contract["schema_version"] == "0.1.0"
    assert contract["command"] == "validation-run"
    assert contract["audience"] == "maintainer_validation_execution"
    assert contract["stability"] == "additive"
    assert {
        "schema_version",
        "validation_run_id",
        "status",
        "summary_path",
        "run_id",
        "next_actions",
    } <= set(contract["stable_fields"])
    assert set(contract["stable_fields"]) <= set(payload)
    SchemaValidator(Path("schemas")).validate("control_surface", contract)


def _assert_validation_run_summary_control_surface(summary: dict) -> None:
    _assert_validation_run_result_control_surface(summary)
    SchemaValidator(Path("schemas")).validate("validation_run", summary)


def test_validation_run_ids_are_unique_within_same_second(tmp_path: Path) -> None:
    command = ValidationRunCommand(tmp_path, dry_run=True)

    first = command._validation_run_id()
    second = command._validation_run_id()

    assert first != second
    assert first.startswith("validation-")
    assert second.startswith("validation-")


def test_validation_run_blocks_until_release_gates_are_ready(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = ValidationRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "blocked"
    _assert_validation_run_result_control_surface(result.to_dict())
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_validation_run_summary_control_surface(summary)
    assert summary["status"] == "blocked"
    assert summary["preflight"]["gate_status"]["stage"] == "missing_real_model_gate"
    assert summary["next_actions"]


def test_validation_run_dry_run_writes_auditable_plan(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "dry_run"
    _assert_validation_run_result_control_surface(result.to_dict())
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_validation_run_summary_control_surface(summary)
    assert summary["dry_run"] is True
    assert summary["preflight"]["sequence"] == [
        "version",
        "package-check",
        "doctor",
        "gate-status",
        "validation-run",
    ]
    assert summary["preflight"]["version"]["package"] == "asteria-runtime"
    assert "package_check" in summary["preflight"]
    assert summary["preflight"]["gate_status"]["stage"] == "ready_for_small_real_task_validation"
    assert summary["route_expectations"]["planning_coordinator"] == "strong"
    assert summary["route_expectations"]["worker"] == "medium"
    assert summary["validation_plan"]["risk_model"] == "adaptive_gates_preserve_agent_flexibility"
    assert (
        summary["validation_plan"]["parallel_writes"]["real_disjoint_write_workers"] == "disabled"
    )
    assert (
        summary["validation_plan"]["parallel_writes"]["enablement_flag"]
        == "real_disjoint_write_workers"
    )
    assert len(summary["validation_plan"]["next_probe_goals"]) == 5
    first_batch_ids = [
        "parent_selects_subagent",
        "readonly_fanout_succeeds",
        "readonly_write_tool_blocked",
        "disjoint_write_gate_blocks_unsafe_fanout",
        "parent_loop_stops_after_observation",
    ]
    second_batch_ids = [
        "repair_replan_path",
        "ask_stop_path",
        "context_pressure_path",
        "capability_selection_path",
    ]
    assert [probe["id"] for probe in summary["validation_plan"]["probes"]] == [
        *first_batch_ids,
        *second_batch_ids,
    ]
    assert [
        item["probe_id"] for item in summary["validation_plan"]["second_batch_probe_goals"]
    ] == second_batch_ids
    assert (
        summary["validation_plan"]["recommended_scoped_validation_batch"]["avoid"]
        == "do_not_repeat_tiny_file_artifact_as_primary_proof"
    )
    disjoint_probe = next(
        probe
        for probe in summary["validation_plan"]["probes"]
        if probe["id"] == "disjoint_write_gate_blocks_unsafe_fanout"
    )
    assert disjoint_probe["gate_policy"] == "strong_block_before_real_parallel_write_enable"


def test_validation_run_can_target_specific_probe_goal(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(
        tmp_path,
        dry_run=True,
        probe_ids=["readonly_fanout_succeeds"],
    ).run()

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["goal"] == summary["validation_plan"]["next_probe_goals"][0]["goal"]
    assert summary["validation_plan"]["selected_probe_ids"] == ["readonly_fanout_succeeds"]
    assert (
        summary["validation_plan"]["next_probe_goals"][0]["probe_id"] == "readonly_fanout_succeeds"
    )
    assert (
        "--probe-id readonly_fanout_succeeds"
        in summary["validation_plan"]["next_probe_goals"][0]["command"]
    )


def test_validation_run_caps_expected_block_probe_iterations(tmp_path: Path) -> None:
    command = ValidationRunCommand(
        tmp_path,
        probe_ids=["readonly_write_tool_blocked"],
        max_iterations=5,
    )

    assert command._effective_max_iterations() == 1


def test_validation_run_caps_runtime_managed_second_batch_probe_iterations(
    tmp_path: Path,
) -> None:
    for probe_id in [
        "repair_replan_path",
        "ask_stop_path",
        "context_pressure_path",
        "capability_selection_path",
    ]:
        command = ValidationRunCommand(
            tmp_path,
            probe_ids=[probe_id],
            max_iterations=5,
        )

        assert command._effective_max_iterations() == 1


def test_validation_run_accepts_current_readonly_fanout_strategy_name(tmp_path: Path) -> None:
    status, summary, refs = ValidationRunCommand(tmp_path, dry_run=True)._probe_status(
        "readonly_fanout_succeeds",
        decisions=[],
        child_plans=[
            {
                "subagent_child_plan_id": "subagent-child-plan-0001",
                "scheduling_strategy": "parallel_readonly_safe",
                "child_tasks": [{"child_task_id": "task-child-1"}],
            }
        ],
        workers=[
            {
                "worker_invocation_id": "worker-child-1",
                "task_id": "task-child-1",
                "parallel_safety": "readonly",
            }
        ],
        worker_results=[
            {
                "worker_invocation_id": "worker-child-1",
                "status": "succeeded",
            }
        ],
        observations=[],
        run_summary={},
    )

    assert status == "passed"
    assert "readonly boundary" in summary
    assert refs == ["subagent-child-plan-0001", "worker-child-1"]


def test_second_batch_probes_evaluate_recovery_ask_context_and_capability(
    tmp_path: Path,
) -> None:
    command = ValidationRunCommand(tmp_path, dry_run=True)

    repair_status, _summary, repair_refs = command._probe_status(
        "repair_replan_path",
        decisions=[_agent_loop_decision("agent-loop-decision-repair", "repair")],
        workers=[],
        worker_results=[],
        child_plans=[],
        observations=[{"summary": "repair observation completed"}],
        execution_results=[_agent_loop_execution("agent-loop-execution-repair", "repair")],
    )
    ask_status, ask_summary, ask_refs = command._probe_status(
        "ask_stop_path",
        decisions=[_agent_loop_decision("agent-loop-decision-ask", "ask")],
        workers=[],
        worker_results=[],
        child_plans=[],
        observations=[],
        execution_results=[_agent_loop_execution("agent-loop-execution-ask", "ask")],
        run_summary={"exit_reason": "ask"},
    )
    request_status, request_summary, request_refs = command._probe_status(
        "ask_stop_path",
        decisions=[],
        workers=[],
        worker_results=[],
        child_plans=[],
        observations=[],
        runtime_requests=[
            {
                "runtime_request_id": "runtime-request-0001",
                "request_type": "context_request",
                "status": "decision_created",
                "decision_id": "decision-0001",
            }
        ],
        decision_points=[
            {
                "decision_id": "decision-0001",
                "status": "pending",
                "metadata": {"kind": "runtime_request"},
            }
        ],
    )
    context_status, _context_summary, context_refs = command._probe_status(
        "context_pressure_path",
        decisions=[],
        workers=[],
        worker_results=[],
        child_plans=[],
        observations=[],
        context_snapshots=[
            {
                "snapshot_id": "context-budget-snapshot-0001",
                "pressure_status": "near_limit",
                "compact_boundary": {"status": "recommended"},
            }
        ],
    )
    capability_status, capability_summary, capability_refs = command._probe_status(
        "capability_selection_path",
        decisions=[],
        workers=[],
        worker_results=[],
        child_plans=[],
        observations=[],
        progress_metrics={
            "permission_reason_coverage": {"with_reason": 1},
            "adapter_invocation_coverage": {
                "mcp_with_reason": 1,
                "skill_with_reason": 0,
                "capability_progress_event_count": 1,
            },
        },
    )

    assert repair_status == "passed"
    assert repair_refs == ["agent-loop-decision-repair", "agent-loop-execution-repair"]
    assert ask_status == "passed"
    assert "exit_reason=ask" in ask_summary
    assert ask_refs == ["agent-loop-decision-ask", "agent-loop-execution-ask"]
    assert request_status == "passed"
    assert "runtime request" in request_summary
    assert request_refs == ["runtime-request-0001", "decision-0001"]
    assert context_status == "passed"
    assert context_refs == ["context-budget-snapshot-0001"]
    assert capability_status == "passed"
    assert "Capability choices" in capability_summary
    assert capability_refs == [
        "capability_decisions.jsonl",
        "mcp_invocations.jsonl",
        "skill_invocations.jsonl",
    ]


def test_validation_run_explains_blocked_route_guidance(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)
    validator = SchemaValidator(Path.cwd() / "schemas")
    JsonStore(validator).write(
        tmp_path / ".asteria" / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "runtime",
                    "model": "medium-route",
                    "purpose": "coding",
                    "model_tier": "medium",
                    "total_calls": 2,
                    "success_calls": 0,
                    "failure_calls": 2,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                }
            ],
        },
        "model_capability_profile",
    )

    result = ValidationRunCommand(tmp_path, dry_run=True).run()

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert result.status == "blocked"
    assert summary["preflight"]["gate_status"]["stage"] == "route_guidance_blocked"
    assert any("route guidance" in action for action in summary["next_actions"])


def test_validation_run_executes_small_task_and_collects_route_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(
        tmp_path,
        goal="Create validation evidence",
        run_command_factory=FakeRunCommand,
    ).run()

    assert result.status == "completed"
    _assert_validation_run_result_control_surface(result.to_dict())
    assert result.run_id == "run-validation-0001"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_validation_run_summary_control_surface(summary)
    assert summary["status"] == "completed"
    assert summary["run_result"]["run_id"] == "run-validation-0001"
    assert summary["evidence"]["route_evidence"]["strong_used"] is True
    assert summary["evidence"]["route_evidence"]["medium_used"] is True
    assert summary["evidence"]["worker_result_count"] == 1
    assert (
        summary["evidence"]["runtime_progress_metrics"]["permission_reason_coverage"][
            "coverage_ratio"
        ]
        == 1.0
    )
    assert summary["evidence"]["runtime_validation_matrix"]["ready"] is True
    assert "recovery_pressure" in summary["evidence"]
    studio_benchmark = summary["evidence"]["studio_runtime_progress_benchmark"]
    assert studio_benchmark["ok"] is True
    assert studio_benchmark["scope"] == "run:run-validation-0001"
    assert summary["validation_plan"]["flexibility_policy"]["low_risk_exploration"] == "trace_only"
    probe_results = {probe["id"]: probe for probe in summary["validation_plan"]["probe_results"]}
    evidence_probe_results = {
        probe["id"]: probe for probe in summary["evidence"]["validation_probe_results"]
    }
    assert probe_results["parent_selects_subagent"]["status"] == "passed"
    assert probe_results["readonly_write_tool_blocked"]["status"] == "passed"
    assert (
        probe_results["disjoint_write_gate_blocks_unsafe_fanout"]["status"]
        == "missing_evidence"
    )
    assert probe_results["parent_loop_stops_after_observation"]["status"] == "passed"
    assert evidence_probe_results == probe_results
    assert any(
        "Review missing validation probe evidence" in action for action in summary["next_actions"]
    )


def test_validation_run_fails_when_studio_runtime_progress_contract_fails(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(
        tmp_path,
        goal="Create validation evidence",
        run_command_factory=BadStudioProgressRunCommand,
    ).run()

    assert result.status == "failed"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    studio_benchmark = summary["evidence"]["studio_runtime_progress_benchmark"]
    assert studio_benchmark["ok"] is False
    assert any(
        "Studio runtime progress contract" in action for action in summary["next_actions"]
    )


def test_validation_run_blocks_multiple_second_batch_runtime_managed_probes(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    class ShouldNotRunCommand:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("runtime-managed probes must be run one at a time")

    result = ValidationRunCommand(
        tmp_path,
        goal="Run multiple second batch probes",
        probe_ids=["repair_replan_path", "ask_stop_path"],
        run_command_factory=ShouldNotRunCommand,
    ).run()

    assert result.status == "blocked"
    assert result.run_id is None
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_validation_run_summary_control_surface(summary)
    assert summary["run_result"] is None
    assert any(
        "one second-batch runtime-managed validation probe" in action
        for action in summary["next_actions"]
    )
    assert "repair_replan_path" in summary["next_actions"][1]
    assert "ask_stop_path" in summary["next_actions"][1]


def test_validation_run_records_structured_failure_when_run_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)
    model_dir = tmp_path / ".asteria" / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "latest_failure.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "failure_type": "network",
                "summary": "provider EOF",
                "recommendations": ["Retry after transient network issues."],
            }
        ),
        encoding="utf-8",
    )

    result = ValidationRunCommand(
        tmp_path,
        goal="Create validation evidence",
        run_command_factory=FailingRunCommand,
    ).run()

    assert result.status == "failed"
    assert result.run_id is None
    assert result.next_actions == ["Retry after transient network issues."]
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_validation_run_summary_control_surface(summary)
    assert summary["status"] == "failed"
    assert summary["run_result"] is None
    failure = summary["evidence"]["execution_failure"]
    assert failure["error_type"] == "RuntimeError"
    assert failure["failure_type"] == "network"
    assert failure["latest_failure"]["summary"] == "provider EOF"


def test_validation_run_treats_absent_disjoint_plan_as_missing_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(
        tmp_path,
        goal="Create simple validation evidence",
        run_command_factory=FakeRunCommandWithoutDisjointPlan,
    ).run()

    assert result.status == "completed"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    probes = {probe["id"]: probe for probe in summary["evidence"]["validation_probe_results"]}
    assert probes["disjoint_write_gate_blocks_unsafe_fanout"]["status"] == "missing_evidence"
    recommended = summary["validation_plan"]["recommended_probe_runs"]
    recommended_by_id = {item["probe_id"]: item for item in recommended}
    assert "disjoint_write_gate_blocks_unsafe_fanout" in recommended_by_id
    assert (
        "--probe-id disjoint_write_gate_blocks_unsafe_fanout"
        in recommended_by_id["disjoint_write_gate_blocks_unsafe_fanout"]["command"]
    )
    assert any(
        "Review missing validation probe evidence" in action for action in summary["next_actions"]
    )


def test_validation_run_fails_when_targeted_probe_remains_missing(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ValidationRunCommand(
        tmp_path,
        goal="Create simple validation evidence",
        probe_ids=["disjoint_write_gate_blocks_unsafe_fanout"],
        run_command_factory=FakeRunCommandWithoutDisjointPlan,
    ).run()

    assert result.status == "failed"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert (
        "Targeted validation probe did not produce required evidence" in summary["next_actions"][0]
    )


def test_targeted_validation_probe_does_not_require_medium_route(tmp_path: Path) -> None:
    result = RunResult(
        run_id="run-validation-0001",
        status="completed",
        final_report_path=tmp_path / "final_report.md",
    )

    status = ValidationRunCommand(
        tmp_path,
        probe_ids=["readonly_fanout_succeeds"],
    )._status_from_run(
        result,
        {
            "route_evidence": {"strong_used": True, "medium_used": False},
            "validation_probe_results": [{"id": "readonly_fanout_succeeds", "status": "passed"}],
        },
    )

    assert status == "completed"


def test_targeted_validation_probe_can_complete_despite_review_blocked_run(
    tmp_path: Path,
) -> None:
    result = RunResult(
        run_id="run-validation-0001",
        status="blocked",
        final_report_path=tmp_path / "final_report.md",
    )

    status = ValidationRunCommand(
        tmp_path,
        probe_ids=["readonly_fanout_succeeds"],
    )._status_from_run(
        result,
        {
            "route_evidence": {"strong_used": True, "medium_used": False},
            "validation_probe_results": [{"id": "readonly_fanout_succeeds", "status": "passed"}],
        },
    )

    assert status == "completed"


class FakeRunCommand:
    def __init__(self, root: Path, **kwargs) -> None:
        self.root = root.resolve()
        self.kwargs = kwargs

    def run(self) -> RunResult:
        run_id = "run-validation-0001"
        run_dir = self.root / ".asteria" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(
            run_dir / "model_calls.jsonl",
            [
                _model_call("call-strong", run_id, "planning", "glm", "glm-5.1", "strong"),
                _model_call("call-medium", run_id, "execute", "minimax", "MiniMax-M2.7", "medium"),
            ],
        )
        _write_jsonl(
            run_dir / "worker_results.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "worker_result_id": "worker-result-0001",
                    "worker_invocation_id": "worker-invocation-0001",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "status": "succeeded",
                    "artifact_refs": ["validation_probe.txt"],
                    "validation_refs": [],
                    "failure_evidence_refs": [],
                    "cost": {"model_calls": 1, "tool_calls": 1},
                    "summary": "Created validation probe.",
                }
            ],
        )
        _write_jsonl(
            run_dir / "task_execution_evidence.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "evidence_id": "task-evidence-0001",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "status": "completed",
                    "summary": "Task completed.",
                    "failure_type": None,
                    "task": {},
                    "action": {},
                    "candidate": {},
                    "contract_check": {},
                    "tool_results": [],
                    "verification_results": [],
                    "created_at": now_iso(),
                }
            ],
        )
        _write_jsonl(
            run_dir / "workers.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "worker_invocation_id": "worker-invocation-0001",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "agent_id": "CoderAgent",
                    "runtime_profile_id": "runtime-profile-subagent",
                    "status": "succeeded",
                    "started_at": now_iso(),
                    "ended_at": now_iso(),
                    "summary": "Subagent validation worker completed.",
                    "worker_kind": "subagent_worker",
                    "parallel_safety": "readonly",
                }
            ],
        )
        _write_jsonl(
            run_dir / "agent_loop_decisions.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "decision_id": "agent-loop-decision-0001",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "created_at": now_iso(),
                    "next_action": {
                        "action": "subagent",
                        "reason": "validate subagent path",
                        "target_task_id": "task-0001",
                        "capability_ref": {"type": "subagent", "name": "CoderAgent"},
                        "expected_observation": {"summary": "subagent result"},
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1},
                        "evidence_refs": [],
                    },
                }
            ],
        )
        _write_jsonl(
            run_dir / "agent_loop_observations.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "observation_id": "agent-loop-observation-0001",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "target_task_id": "task-0001",
                    "created_at": now_iso(),
                    "observation_type": "subagent_result",
                    "source_execution_id": "agent-loop-execution-0001",
                    "source_decision_id": "agent-loop-decision-0001",
                    "status": "succeeded",
                    "summary": "subagent result; readonly write tool denied",
                    "evidence_refs": ["worker_results.jsonl"],
                    "next_recommended_action": "stop",
                }
            ],
        )
        _write_jsonl(
            run_dir / "subagent_child_plans.jsonl",
            [_disjoint_write_plan(run_id)],
        )
        (run_dir / "agent_loop_run_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": run_id,
                    "task_id": "task-0001",
                    "created_at": now_iso(),
                    "status": "completed",
                    "exit_reason": "completed",
                    "rounds_completed": 1,
                    "max_rounds": 2,
                    "summary": "Parent loop stopped after subagent observation.",
                    "recommended_command": None,
                    "latest_decision_id": "agent-loop-decision-0001",
                    "latest_execution_id": "agent-loop-execution-0001",
                    "latest_observation_id": "agent-loop-observation-0001",
                    "latest_action": "stop",
                    "evidence_refs": ["agent_loop_observations.jsonl"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "agent_loop_dispatch.json").write_text(
            json.dumps(
                {
                    "profile_counts": {
                        "research": 1,
                        "brainstorm": 1,
                        "multi_agent": 1,
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_jsonl(
            run_dir / "capability_decisions.jsonl",
            [
                {
                    "decision": {
                        "decision": "ask",
                        "reason": "capability is available but requires a decision",
                    }
                }
            ],
        )
        _write_jsonl(
            run_dir / "mcp_invocations.jsonl",
            [{"mcp_invocation_id": "mcp-1", "capability_decision": {"reason": "echo allowed"}}],
        )
        _write_jsonl(
            run_dir / "skill_invocations.jsonl",
            [
                {
                    "skill_invocation_id": "skill-1",
                    "capability_decision": {"reason": "artifact skill selected"},
                }
            ],
        )
        _write_jsonl(
            run_dir / "user_progress.jsonl",
            _semantic_user_progress(run_id),
        )
        (run_dir / "cost_report.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": run_id,
                    "model_calls": 2,
                    "tool_calls": 1,
                    "estimated_input_tokens": 10,
                    "estimated_output_tokens": 5,
                    "strong_model_calls": 1,
                    "cheap_model_calls": 0,
                    "repair_attempts": 0,
                    "research_calls": 0,
                    "context_compactions": 0,
                    "user_decisions": 0,
                    "status": "within_budget",
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        return RunResult(
            run_id=run_id,
            status="completed",
            final_report_path=run_dir / "final_report.md",
            steps=[RunStepSummary("execute", "completed", "fake validation execution")],
        )


class FakeRunCommandWithoutDisjointPlan(FakeRunCommand):
    def run(self) -> RunResult:
        result = super().run()
        run_dir = self.root / ".asteria" / "runs" / result.run_id
        (run_dir / "subagent_child_plans.jsonl").unlink()
        return result


class FailingRunCommand:
    def __init__(self, **kwargs) -> None:
        self.root = kwargs["root"]

    def run(self) -> RunResult:
        raise RuntimeError("GoalSpec model call failed with network")


class BadStudioProgressRunCommand(FakeRunCommand):
    def run(self) -> RunResult:
        result = super().run()
        run_dir = self.root / ".asteria" / "runs" / result.run_id
        _write_jsonl(
            run_dir / "user_progress.jsonl",
            [
                {
                    "schema_version": "0.1.0",
                    "event_id": "upe-bad-1",
                    "run_id": result.run_id,
                    "created_at": now_iso(),
                    "channel": "model",
                    "event_type": "delta",
                    "phase": "execute",
                    "status": "running",
                    "title": "Raw model",
                    "summary": "raw",
                    "content_delta": "<think>raw provider trace</think>",
                    "display_level": "main",
                    "transcript_kind": "assistant_message",
                    "artifact_refs": [],
                    "evidence_refs": [],
                    "call_chain": [],
                    "execution_chain": [],
                    "file_changes": [],
                    "data": {},
                }
            ],
        )
        return result


def _write_ready_gate_reports(root: Path) -> None:
    model_dir = root / ".asteria" / "model"
    verification_dir = root / ".asteria" / "verification"
    model_dir.mkdir(parents=True, exist_ok=True)
    verification_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "validation_ready": True,
                "aggregate": {
                    "total": 4,
                    "passed": 4,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 6, "passed": 6}}),
        encoding="utf-8",
    )


def _semantic_user_progress(run_id: str) -> list[dict]:
    base = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "created_at": now_iso(),
        "phase": "execute",
        "status": "completed",
        "display_level": "main",
        "artifact_refs": [],
        "evidence_refs": [],
        "call_chain": [],
        "execution_chain": [],
        "file_changes": [],
        "data": {},
    }
    events = [
        ("upe-plan", "progress", "start", "plan", "Plan ready", "Validation task is planned."),
        ("upe-tool-use", "tool", "tool_call", "tool_use", "Using tool", "Writing validation artifact."),
        ("upe-tool-result", "tool", "tool_observation", "tool_result", "Tool result", "Validation artifact was written."),
        ("upe-file", "file", "file_changed", "file_change", "File changed", "Updated validation_probe.txt."),
        ("upe-verify", "validation", "validation_result", "verification", "Verification passed", "Validation checks passed."),
        ("upe-final", "conclusion", "final_report", "final", "Result ready", "Validation run summary is ready."),
    ]
    payloads = []
    for event_id, channel, event_type, transcript_kind, title, summary in events:
        item = {
            **base,
            "event_id": event_id,
            "channel": channel,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "transcript_kind": transcript_kind,
        }
        if transcript_kind == "file_change":
            item["file_changes"] = [{"path": "validation_probe.txt", "operation": "modified"}]
        payloads.append(item)
    payloads.append(
        {
            **base,
            "event_id": "upe-capability",
            "channel": "permission",
            "event_type": "permission_decision",
            "title": "Capability decision recorded",
            "summary": "recorded",
            "transcript_kind": "permission_request",
            "data": {"capability_type": "skill"},
        }
    )
    return payloads


def _configure_release_routes(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_STRONG_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "MiniMax-M2.7")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-key")


def _model_call(
    model_call_id: str,
    run_id: str,
    purpose: str,
    provider: str,
    model_name: str,
    tier: str,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "model_call_id": model_call_id,
        "run_id": run_id,
        "agent_id": None,
        "runtime_profile_id": None,
        "model_profile_id": None,
        "purpose": purpose,
        "model_provider": provider,
        "model_name": model_name,
        "model_tier": tier,
        "input_tokens": 1,
        "output_tokens": 1,
        "status": "success",
        "created_at": now_iso(),
        "summary": "fake call",
    }


def _agent_loop_decision(decision_id: str, action: str) -> dict:
    return {
        "decision_id": decision_id,
        "next_action": {"action": action},
    }


def _agent_loop_execution(execution_id: str, action: str) -> dict:
    target = {
        "repair": "debug_agent",
        "replan": "replan_command",
        "ask": "decision_point",
        "stop": "stop_report",
    }.get(action, "tool_gateway")
    return {
        "execution_id": execution_id,
        "action": action,
        "target": target,
    }


def _disjoint_write_plan(run_id: str) -> dict:
    children = []
    for index, file_name in ((1, "docs/a.md"), (2, "docs/b.md")):
        children.append(
            {
                "child_task_id": f"task-1-write-{index:02d}",
                "task_id": "task-0001",
                "title": f"Write shard {index}",
                "objective": f"Write {file_name}.",
                "acceptance": [f"{file_name} written"],
                "read_scope": ["."],
                "write_scope": [file_name],
                "allowed_tools": ["write_file", "run_command"],
                "depends_on": [],
                "risk": "medium",
                "parallel_safety": "disjoint_writes",
                "worker_role": "implementation_child",
                "write_allowed": True,
                "expected_output": [file_name],
                "verification_expectation": {"requires_verification": True},
            }
        )
    return {
        "schema_version": "0.1.0",
        "subagent_child_plan_id": "subagent-child-plan-0001",
        "run_id": run_id,
        "parent_task_id": "task-parent",
        "target_task_id": "task-0001",
        "parent_decision_id": "agent-loop-decision-0001",
        "parent_execution_id": "agent-loop-execution-0001",
        "worker_invocation_id": "worker-invocation-0001",
        "worker_result_id": "worker-result-0001",
        "runtime_profile_id": "runtime-profile-subagent",
        "planner_id": "RuntimeSubagentPlanner",
        "decomposition_strategy": "disjoint_write_child_tasks",
        "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
        "max_child_workers": 2,
        "coordination_policy": {
            "write_allowed": True,
            "requires_merge_gate": True,
            "requires_disjoint_write_scope": True,
        },
        "status": "planned",
        "parallel_safety": "disjoint_writes",
        "child_tasks": children,
        "evidence_refs": ["agent_loop_execution_results.jsonl"],
        "created_at": now_iso(),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
