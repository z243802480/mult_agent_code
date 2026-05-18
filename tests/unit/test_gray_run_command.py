from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.gray_run_command import GrayRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunResult, RunStepSummary
from asteria_runtime.utils.time import now_iso


def test_gray_run_blocks_until_release_gates_are_ready(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = GrayRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "blocked"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert summary["preflight"]["gate_status"]["stage"] == "missing_real_model_gate"
    assert summary["next_actions"]


def test_gray_run_dry_run_writes_auditable_plan(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = GrayRunCommand(tmp_path, dry_run=True).run()

    assert result.status == "dry_run"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["dry_run"] is True
    assert summary["preflight"]["sequence"] == [
        "version",
        "package-check",
        "doctor",
        "gate-status",
        "gray-run",
    ]
    assert summary["preflight"]["version"]["package"] == "asteria-runtime"
    assert "package_check" in summary["preflight"]
    assert summary["preflight"]["gate_status"]["stage"] == "ready_for_small_real_task_gray"
    assert summary["route_expectations"]["planning_coordinator"] == "strong"
    assert summary["route_expectations"]["worker"] == "medium"


def test_gray_run_executes_small_task_and_collects_route_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    _configure_release_routes(monkeypatch)
    _write_ready_gate_reports(tmp_path)

    result = GrayRunCommand(
        tmp_path,
        goal="Create gray evidence",
        run_command_factory=FakeRunCommand,
    ).run()

    assert result.status == "completed"
    assert result.run_id == "run-gray-0001"
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["run_result"]["run_id"] == "run-gray-0001"
    assert summary["evidence"]["route_evidence"]["strong_used"] is True
    assert summary["evidence"]["route_evidence"]["medium_used"] is True
    assert summary["evidence"]["worker_result_count"] == 1


class FakeRunCommand:
    def __init__(self, root: Path, **kwargs) -> None:
        self.root = root.resolve()
        self.kwargs = kwargs

    def run(self) -> RunResult:
        run_id = "run-gray-0001"
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
                    "artifact_refs": ["gray_probe.txt"],
                    "validation_refs": [],
                    "failure_evidence_refs": [],
                    "cost": {"model_calls": 1, "tool_calls": 1},
                    "summary": "Created gray probe.",
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
            steps=[RunStepSummary("execute", "completed", "fake gray execution")],
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
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "gray_ready": True,
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
