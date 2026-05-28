from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.readiness_run_command import ReadinessRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunResult, RunStepSummary
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def _assert_readiness_run_result_control_surface(payload: dict) -> None:
    contract = payload["control_surface"]

    assert payload["schema_version"] == "0.1.0"
    assert contract["schema_version"] == "0.1.0"
    assert contract["command"] == "readiness-run"
    assert contract["audience"] == "maintainer_readiness_execution"
    assert contract["stability"] == "additive"
    assert {
        "schema_version",
        "readiness_run_id",
        "status",
        "summary_path",
        "run_id",
        "next_actions",
    } <= set(contract["stable_fields"])
    assert set(contract["stable_fields"]) <= set(payload)
    SchemaValidator(Path("schemas")).validate("control_surface", contract)



def _assert_readiness_run_summary_control_surface(summary: dict) -> None:
    _assert_readiness_run_result_control_surface(summary)
    SchemaValidator(Path("schemas")).validate("readiness_run", summary)

def test_readiness_run_blocks_until_release_gates_are_ready(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = ReadinessRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "blocked"
    _assert_readiness_run_result_control_surface(result.to_dict())
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_readiness_run_summary_control_surface(summary)
    assert summary["status"] == "blocked"
    assert summary["preflight"]["gate_status"]["stage"] == "missing_real_model_gate"
    assert summary["next_actions"]


def test_readiness_run_dry_run_writes_auditable_plan(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ReadinessRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "dry_run"
    _assert_readiness_run_result_control_surface(result.to_dict())
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_readiness_run_summary_control_surface(summary)
    assert summary["dry_run"] is True
    assert summary["preflight"]["sequence"] == [
        "version",
        "package-check",
        "doctor",
        "gate-status",
        "readiness-run",
    ]
    assert summary["preflight"]["version"]["package"] == "asteria-runtime"
    assert "package_check" in summary["preflight"]
    assert summary["preflight"]["gate_status"]["stage"] == "ready_for_small_real_task_readiness"
    assert summary["route_expectations"]["planning_coordinator"] == "strong"
    assert summary["route_expectations"]["worker"] == "medium"


def test_readiness_run_explains_blocked_route_guidance(
    tmp_path: Path, monkeypatch
) -> None:
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

    result = ReadinessRunCommand(tmp_path, dry_run=True).run()

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert result.status == "blocked"
    assert summary["preflight"]["gate_status"]["stage"] == "route_guidance_blocked"
    assert any("route guidance" in action for action in summary["next_actions"])


def test_readiness_run_executes_small_task_and_collects_route_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = ReadinessRunCommand(
        tmp_path,
        goal="Create readiness evidence",
        run_command_factory=FakeRunCommand,
    ).run()

    assert result.status == "completed"
    _assert_readiness_run_result_control_surface(result.to_dict())
    assert result.run_id == "run-readiness-0001"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    _assert_readiness_run_summary_control_surface(summary)
    assert summary["status"] == "completed"
    assert summary["run_result"]["run_id"] == "run-readiness-0001"
    assert summary["evidence"]["route_evidence"]["strong_used"] is True
    assert summary["evidence"]["route_evidence"]["medium_used"] is True
    assert summary["evidence"]["worker_result_count"] == 1
    assert summary["evidence"]["runtime_progress_metrics"]["permission_reason_coverage"][
        "coverage_ratio"
    ] == 1.0
    assert summary["evidence"]["runtime_readiness_matrix"]["ready"] is True
    assert "recovery_pressure" in summary["evidence"]


class FakeRunCommand:
    def __init__(self, root: Path, **kwargs) -> None:
        self.root = root.resolve()
        self.kwargs = kwargs

    def run(self) -> RunResult:
        run_id = "run-readiness-0001"
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
                    "artifact_refs": ["readiness_probe.txt"],
                    "validation_refs": [],
                    "failure_evidence_refs": [],
                    "cost": {"model_calls": 1, "tool_calls": 1},
                    "summary": "Created readiness probe.",
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
            [
                {
                    "schema_version": "0.1.0",
                    "event_id": "upe-1",
                    "run_id": run_id,
                    "created_at": now_iso(),
                    "channel": "permission",
                    "event_type": "permission_decision",
                    "phase": "execute",
                    "status": "running",
                    "title": "Capability decision recorded",
                    "summary": "recorded",
                    "display_level": "main",
                    "artifact_refs": [],
                    "evidence_refs": [],
                    "call_chain": [],
                    "execution_chain": [],
                    "file_changes": [],
                    "data": {"capability_type": "skill"},
                }
            ],
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
            steps=[RunStepSummary("execute", "completed", "fake readiness execution")],
        )


def _write_ready_gate_reports(root: Path) -> None:
    model_dir = root / ".asteria" / "model"
    verification_dir = root / ".asteria" / "verification"
    model_dir.mkdir(parents=True, exist_ok=True)
    verification_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_readiness.json").write_text(
        json.dumps(
            {
                "ok": True,
                "readiness_ready": True,
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


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
