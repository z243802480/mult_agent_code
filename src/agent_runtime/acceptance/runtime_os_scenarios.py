from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_runtime.acceptance.runtime_os_catalog import runtime_os_capability_map
from agent_runtime.utils.time import now_iso

REPO_ROOT = Path(__file__).resolve().parents[3]


class RuntimeAcceptanceClient:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.seen_context_package: dict[str, Any] = {}

    def chat(self, request: Any) -> Any:
        from agent_runtime.models.base import ChatResponse, TokenUsage

        payload = json.loads(request.messages[-1].content)
        task = payload["task"]
        task_id = task["task_id"]
        if self.mode == "readonly":
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": f"Verify readonly task {task_id}.",
                "tool_calls": [],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {"command": f"python -c \"print('{task_id} readonly ok')\""},
                        "reason": "readonly verification",
                    }
                ],
                "completion_notes": f"{task_id} verified without writes",
            }
        elif self.mode == "disjoint":
            path = "out/alpha.txt" if task_id == "task-0001" else "out/beta.txt"
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": f"Write {path}.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": path, "content": task_id, "overwrite": True},
                        "reason": "write disjoint output",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": (
                                "python -c \"from pathlib import Path; "
                                f"assert Path('{path}').read_text(encoding='utf-8') == '{task_id}'\""
                            )
                        },
                        "reason": "verify output",
                    }
                ],
                "completion_notes": f"{path} verified",
            }
        elif self.mode == "failure":
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Create an intentionally failing candidate.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "blocked/output.txt",
                            "content": "wrong",
                            "overwrite": True,
                        },
                        "reason": "create candidate",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": (
                                "python -c \"from pathlib import Path; "
                                "assert Path('blocked/output.txt').read_text(encoding='utf-8') == 'expected'\""
                            )
                        },
                        "reason": "force verification failure",
                    }
                ],
                "completion_notes": "candidate should be discarded",
            }
        elif self.mode == "runtime_request":
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Request a write outside the current contract.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "requested/output.txt",
                            "content": "needs scope",
                            "overwrite": True,
                        },
                        "reason": "exercise runtime request",
                    }
                ],
                "verification": [],
                "completion_notes": "runtime request expected",
            }
        elif self.mode == "context_package":
            package = payload.get("runtime_context", {}).get("context_package", {})
            read_files = package.get("read_scope_files") if isinstance(package, dict) else []
            read_files = read_files if isinstance(read_files, list) else []
            paths = [
                str(item.get("path"))
                for item in read_files
                if isinstance(item, dict) and item.get("path")
            ]
            self.seen_context_package = {
                "paths": paths,
                "has_scoped_file": "input/scoped.txt" in paths,
                "has_unscoped_file": "input/unscoped.txt" in paths,
            }
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Use sliced context package input.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "out/context.txt",
                            "content": "sliced context observed",
                            "overwrite": True,
                        },
                        "reason": "write scoped output",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": (
                                "python -c \"from pathlib import Path; "
                                "assert Path('out/context.txt').read_text(encoding='utf-8') "
                                "== 'sliced context observed'\""
                            )
                        },
                        "reason": "verify sliced context output",
                    }
                ],
                "completion_notes": "context package slice verified",
            }
        elif self.mode == "planner_scope":
            action = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Request the narrowed planner scope to be expanded.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [
                    {
                        "request_type": "scope_expansion",
                        "risk": "medium",
                        "reason": "Planner intentionally withheld broad write_scope.",
                        "details": {"write_scope": ["src/runtime_scope_target.py"]},
                    }
                ],
                "completion_notes": "runtime request expected",
            }
        elif self.mode == "feedback":
            if task_id == "task-0001":
                action = {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Create feedback validation artifact.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "out/feedback.txt",
                                "content": "feedback",
                                "overwrite": True,
                            },
                            "reason": "write feedback artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c \"from pathlib import Path; "
                                    "assert Path('out/feedback.txt').read_text(encoding='utf-8') "
                                    "== 'feedback'\""
                                )
                            },
                            "reason": "verify feedback artifact",
                        }
                    ],
                    "completion_notes": "feedback validation passed",
                }
            else:
                action = {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Request feedback scope expansion.",
                    "tool_calls": [],
                    "verification": [],
                    "runtime_requests": [
                        {
                            "request_type": "scope_expansion",
                            "risk": "medium",
                            "reason": "Collect runtime request signal for capability feedback.",
                            "details": {"write_scope": ["out/feedback-request.txt"]},
                        }
                    ],
                    "completion_notes": "runtime feedback request expected",
                }
        else:
            raise ValueError(f"Unknown runtime acceptance mode: {self.mode}")
        return ChatResponse(
            content=json.dumps(action, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="runtime-acceptance",
            model_name=self.mode,
            raw_response={},
        )


class RuntimeEvidenceDebugClient:
    def __init__(self) -> None:
        self.consumed_runtime_evidence = False

    def chat(self, request: Any) -> Any:
        from agent_runtime.models.base import ChatResponse, TokenUsage

        payload = json.loads(request.messages[-1].content)
        task = payload["task"]
        evidence = payload.get("failure_evidence", {})
        runtime_evidence = evidence.get("runtime_os_evidence")
        self.consumed_runtime_evidence = bool(
            isinstance(runtime_evidence, dict)
            and runtime_evidence.get("worker_results")
            and runtime_evidence.get("task_execution_evidence")
        )
        action = {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Repair using Runtime OS evidence.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "blocked/output.txt",
                        "content": "expected",
                        "overwrite": True,
                    },
                    "reason": "repair failed worker output",
                }
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            "python -c \"from pathlib import Path; "
                            "assert Path('blocked/output.txt').read_text(encoding='utf-8') == 'expected'\""
                        )
                    },
                    "reason": "verify repaired output",
                }
            ],
            "completion_notes": "Runtime evidence guided repair",
        }
        return ChatResponse(
            content=json.dumps(action, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="runtime-acceptance",
            model_name="runtime-evidence-debug",
            raw_response={},
        )


class RuntimeEvidenceReviewClient:
    def __init__(self) -> None:
        self.consumed_runtime_evidence = False

    def chat(self, request: Any) -> Any:
        from agent_runtime.models.base import ChatResponse, TokenUsage

        payload = json.loads(request.messages[-1].content)
        trajectory = payload.get("trajectory", {})
        checks = payload.get("deterministic_checks", {})
        self.consumed_runtime_evidence = bool(
            isinstance(trajectory.get("runtime_os_evidence"), dict)
            and trajectory.get("worker_results")
            and "runtime_os_summary" in checks
        )
        report = {
            "schema_version": "0.1.0",
            "run_id": payload["run_id"],
            "goal_eval": {"goal_clarity_score": 0.9, "requirement_coverage": 1.0},
            "artifact_eval": {"artifacts_present": True, "logs_present": True},
            "outcome_eval": {"verification_pass_rate": 1.0, "run_success": True},
            "trajectory_eval": {"blocked_task_count": 0, "repair_success_rate": 1.0},
            "cost_eval": {"status": "within_budget", "model_calls": 3, "tool_calls": 4},
            "overall": {
                "status": "pass",
                "score": 0.9,
                "reason": "Runtime OS evidence proves repair and review.",
            },
        }
        return ChatResponse(
            content=json.dumps(report, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="runtime-acceptance",
            model_name="runtime-evidence-review",
            raw_response={},
        )


def run_runtime_os_scenario(
    workspace: Path,
    scenario_name: str,
    capability: str,
    tier: str,
) -> dict[str, Any]:
    started_at = time.monotonic()
    if len(str(workspace)) > 120:
        workspace = Path(tempfile.mkdtemp(prefix=f"rtos-{scenario_name[:8]}-")).resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    try:
        if scenario_name == "runtime_parallel_readonly":
            ok, summary = _runtime_parallel_readonly(workspace)
        elif scenario_name == "runtime_disjoint_writes":
            ok, summary = _runtime_disjoint_writes(workspace)
        elif scenario_name == "runtime_worker_failure":
            ok, summary = _runtime_worker_failure(workspace)
        elif scenario_name == "runtime_merge_gate_block":
            ok, summary = _runtime_merge_gate_block(workspace)
        elif scenario_name == "runtime_request_resume":
            ok, summary = _runtime_request_resume(workspace)
        elif scenario_name == "runtime_context_package_slice":
            ok, summary = _runtime_context_package_slice(workspace)
        elif scenario_name == "runtime_sandbox_backend_selection":
            ok, summary = _runtime_sandbox_backend_selection(workspace)
        elif scenario_name == "runtime_planner_scope_quality":
            ok, summary = _runtime_planner_scope_quality(workspace)
        elif scenario_name == "runtime_capability_feedback":
            ok, summary = _runtime_capability_feedback(workspace)
        elif scenario_name == "runtime_evidence_consumption":
            ok, summary = _runtime_evidence_consumption(workspace)
        else:
            raise ValueError(f"Unknown runtime OS scenario: {scenario_name}")
    except Exception as exc:  # noqa: BLE001 - scenario summary should preserve diagnostics
        ok = False
        summary = {"error": str(exc), "runtime_os": {"capability": capability}}
    return {
        "scenario": scenario_name,
        "capability": capability,
        "tier": tier,
        "ok": ok,
        "workspace": str(workspace),
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "summary": summary,
        "stdout": json.dumps(summary, ensure_ascii=False),
        "stderr": "" if ok else str(summary.get("error") or "runtime OS scenario failed"),
    }


def runtime_os_acceptance_scenarios() -> dict[str, dict[str, str]]:
    return {
        item.scenario: {
            "name": item.scenario,
            "capability": item.capability,
            "tier": item.tier,
            "kind": item.kind,
        }
        for item in runtime_os_capability_map().values()
    }


def _runtime_parallel_readonly(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task("task-0001", "Readonly alpha", readonly=True),
            _runtime_task("task-0002", "Readonly beta", readonly=True),
        ],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        max_tasks=2,
        model_client=RuntimeAcceptanceClient("readonly"),
        parallel_readonly=True,
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    worker_results = _read_jsonl(run_dir / "worker_results.jsonl")
    ok = result.completed == 2 and len(worker_results) == 2 and all(
        item.get("status") == "succeeded" for item in worker_results
    )
    return ok, _runtime_summary("runtime_parallel_readonly", run_id, evidence, result=result.to_text())


def _runtime_disjoint_writes(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task("task-0001", "Write alpha", write_scope=["out/alpha.txt"], disjoint=True),
            _runtime_task("task-0002", "Write beta", write_scope=["out/beta.txt"], disjoint=True),
        ],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        max_tasks=2,
        model_client=RuntimeAcceptanceClient("disjoint"),
        parallel_writes=True,
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    ok = (
        result.completed == 2
        and (workspace / "out" / "alpha.txt").read_text(encoding="utf-8") == "task-0001"
        and (workspace / "out" / "beta.txt").read_text(encoding="utf-8") == "task-0002"
    )
    return ok, _runtime_summary("runtime_disjoint_writes", run_id, evidence, result=result.to_text())


def _runtime_worker_failure(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task(
                "task-0001",
                "Fail isolated worker",
                write_scope=["blocked/output.txt"],
            )
        ],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("failure"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    evidence["candidate_isolated"] = not (workspace / "blocked" / "output.txt").exists()
    evidence["failure_evidence"] = bool(_read_jsonl(run_dir / "task_failures.jsonl"))
    worker_results = _read_jsonl(run_dir / "worker_results.jsonl")
    ok = (
        result.blocked == 1
        and evidence["candidate_isolated"]
        and evidence["failure_evidence"]
        and bool(worker_results)
        and worker_results[-1].get("status") == "failed"
    )
    return ok, _runtime_summary("runtime_worker_failure", run_id, evidence, result=result.to_text())


def _runtime_merge_gate_block(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand
    from agent_runtime.core.merge_gate import MergeGate

    run_id = _seed_runtime_run(
        workspace,
        [_runtime_task("task-0001", "Prime runtime records", readonly=True)],
    )
    ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("readonly"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)

    class Result:
        ok = True
        summary = "passed"

    gate = MergeGate().evaluate(
        {"write_scope": ["safe/output.txt"], "completion_contract": {"requires_changed_artifact": True}},
        ["safe/output.txt", "unsafe/output.txt"],
        [Result()],
    )
    evidence["merge_gate_blocked"] = not gate.ok and "unsafe/output.txt" in "; ".join(gate.violations)
    ok = bool(evidence["merge_gate_blocked"])
    summary = _runtime_summary("runtime_merge_gate_block", run_id, evidence)
    summary["runtime_os"]["merge_gate"] = gate.to_dict()
    return ok, summary


def _runtime_request_resume(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.decide_command import DecideCommand
    from agent_runtime.commands.execute_command import ExecuteCommand
    from agent_runtime.commands.resume_command import ResumeCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task(
                "task-0001",
                "Request runtime scope",
                write_scope=["allowed/output.txt"],
            )
        ],
    )
    execute = ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("runtime_request"),
    ).run()
    DecideCommand(
        workspace,
        run_id=run_id,
        decision_id="decision-0001",
        select_option_id="reject_request",
    ).run()
    resumed = ResumeCommand(
        workspace,
        run_id=run_id,
        max_iterations=1,
        execute_model_client=RuntimeAcceptanceClient("runtime_request"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    evidence["resume_recovered"] = resumed.applied_decisions == 1
    evidence["failure_evidence"] = bool(_read_jsonl(run_dir / "task_failures.jsonl"))
    ok = execute.blocked == 1 and evidence["resume_recovered"]
    return ok, _runtime_summary(
        "runtime_request_resume",
        run_id,
        evidence,
        result=resumed.to_text(),
    )


def _runtime_context_package_slice(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand

    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "scoped.txt").write_text("keep me", encoding="utf-8")
    (workspace / "input" / "unscoped.txt").write_text("omit me", encoding="utf-8")
    task = _runtime_task(
        "task-0001",
        "Use sliced context",
        write_scope=["out/context.txt"],
    )
    task["read_scope"] = ["input/scoped.txt"]
    run_id = _seed_runtime_run(workspace, [task])
    client = RuntimeAcceptanceClient("context_package")
    result = ExecuteCommand(workspace, run_id=run_id, model_client=client).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    evidence["context_package_sliced"] = bool(
        client.seen_context_package.get("has_scoped_file")
        and not client.seen_context_package.get("has_unscoped_file")
    )
    ok = (
        result.completed == 1
        and evidence["context_package_sliced"]
        and (workspace / "out" / "context.txt").read_text(encoding="utf-8")
        == "sliced context observed"
    )
    summary = _runtime_summary("context_package_slice", run_id, evidence, result=result.to_text())
    summary["runtime_os"]["context_package"] = client.seen_context_package
    return ok, summary


def _runtime_sandbox_backend_selection(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [_runtime_task("task-0001", "Select sandbox backend", write_scope=["out/alpha.txt"])],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("disjoint"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    sandbox_profiles = _read_jsonl(run_dir / "sandbox_profiles.jsonl")
    recorded = [
        item
        for item in sandbox_profiles
        if item.get("backend") in {"git_worktree", "temp_workspace", "single_workspace"}
        and item.get("reason")
    ]
    evidence["sandbox_backend_recorded"] = bool(recorded)
    ok = result.completed == 1 and evidence["sandbox_backend_recorded"]
    summary = _runtime_summary(
        "sandbox_backend_selection",
        run_id,
        evidence,
        result=result.to_text(),
    )
    summary["runtime_os"]["sandbox_profiles"] = recorded[-3:]
    return ok, summary


def _runtime_planner_scope_quality(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.agents.planner import RequirementPlanner
    from agent_runtime.commands.execute_command import ExecuteCommand

    goal_spec = {
        "schema_version": "0.1.0",
        "goal_id": "goal-runtime-os",
        "original_goal": "Improve the src package behavior.",
        "normalized_goal": "Improve the src package behavior.",
        "goal_type": "codebase_improvement",
        "assumptions": [],
        "constraints": [],
        "non_goals": [],
        "expanded_requirements": [
            {
                "id": "req-runtime-scope",
                "priority": "must",
                "description": "Improve behavior across src without a known concrete file.",
                "acceptance": ["Behavior improvement is implemented and verified."],
                "expected_artifacts": ["src/"],
            }
        ],
        "target_outputs": ["src/"],
        "definition_of_done": ["Behavior improvement is implemented and verified."],
        "verification_strategy": ["local command"],
        "budget": {"max_iterations": 2, "max_model_calls": 10},
    }
    planned_task = RequirementPlanner().build_task_plan(goal_spec)["tasks"][0]
    planned_task["status"] = "ready"
    run_id = _seed_runtime_run(workspace, [planned_task])
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("planner_scope"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    runtime_requests = _read_jsonl(run_dir / "runtime_requests.jsonl")
    notes = str(planned_task.get("notes", "")).lower()
    evidence["planner_scope_narrowed"] = (
        planned_task.get("write_scope") == []
        and "scope quality" in notes
        and "scope request" in notes
    )
    evidence["runtime_request_created"] = any(
        item.get("request_type") == "scope_expansion" for item in runtime_requests
    )
    ok = result.blocked == 1 and evidence["planner_scope_narrowed"] and evidence["runtime_request_created"]
    summary = _runtime_summary("planner_scope_quality", run_id, evidence, result=result.to_text())
    summary["runtime_os"]["planned_task"] = {
        "write_scope": planned_task.get("write_scope"),
        "parallel_safety": planned_task.get("parallel_safety"),
        "notes": planned_task.get("notes"),
    }
    return ok, summary


def _runtime_capability_feedback(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.capability_report_command import CapabilityReportCommand
    from agent_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task("task-0001", "Collect validation signal", write_scope=["out/feedback.txt"]),
            _runtime_task(
                "task-0002",
                "Collect runtime request signal",
                write_scope=["out/feedback-request.txt"],
            ),
        ],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        max_tasks=2,
        model_client=RuntimeAcceptanceClient("feedback"),
    ).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    _append_merge_gate_feedback(run_dir, run_id)
    report = CapabilityReportCommand(workspace).run()
    profiles = report.model_profiles
    profile = next(
        (
            item
            for item in profiles
            if item.get("provider") == "runtime"
            and item.get("model") == "medium-route"
            and item.get("purpose") == "coding"
        ),
        {},
    )
    evidence = _runtime_evidence(run_dir)
    evidence["capability_feedback_recorded"] = bool(
        profile
        and int(profile.get("runtime_request_total") or 0) >= 1
        and int(profile.get("merge_gate_blocks") or 0) >= 1
        and int(profile.get("validation_total") or 0) >= 1
    )
    ok = result.completed == 1 and result.blocked == 1 and evidence["capability_feedback_recorded"]
    summary = _runtime_summary("capability_feedback", run_id, evidence, result=report.to_text())
    summary["runtime_os"]["capability_profile"] = profile
    return ok, summary


def _append_merge_gate_feedback(run_dir: Path, run_id: str) -> None:
    from agent_runtime.storage.jsonl_store import JsonlStore
    from agent_runtime.storage.schema_validator import SchemaValidator

    validator = SchemaValidator(REPO_ROOT / "schemas")
    JsonlStore(validator).append(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "evidence-merge-feedback",
            "run_id": run_id,
            "task_id": "task-0001",
            "status": "blocked",
            "summary": "Synthetic merge gate signal for capability feedback acceptance.",
            "failure_type": "merge_gate",
            "task": {"task_id": "task-0001"},
            "action": {"summary": "feedback merge gate"},
            "candidate": {"changed_files": ["out/feedback.txt", "unsafe/feedback.txt"]},
            "contract_check": {
                "ok": False,
                "changed_files": ["out/feedback.txt", "unsafe/feedback.txt"],
                "merge_gate": {
                    "ok": False,
                    "summary": "unsafe/feedback.txt outside write_scope",
                    "violations": ["unsafe/feedback.txt outside write_scope"],
                    "promotable_files": ["out/feedback.txt"],
                },
            },
            "tool_results": [],
            "verification_results": [],
            "created_at": now_iso(),
        },
        "task_execution_evidence",
    )


def _runtime_evidence_consumption(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from agent_runtime.commands.debug_command import DebugCommand
    from agent_runtime.commands.execute_command import ExecuteCommand
    from agent_runtime.commands.review_command import ReviewCommand

    run_id = _seed_runtime_run(
        workspace,
        [
            _runtime_task(
                "task-0001",
                "Repair and review Runtime OS evidence",
                write_scope=["blocked/output.txt"],
            )
        ],
    )
    ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("failure"),
    ).run()
    debug_client = RuntimeEvidenceDebugClient()
    DebugCommand(workspace, run_id=run_id, model_client=debug_client).run()
    review_client = RuntimeEvidenceReviewClient()
    ReviewCommand(workspace, run_id=run_id, model_client=review_client).run()
    run_dir = workspace / ".agent" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    evidence["debug_consumed_runtime_evidence"] = debug_client.consumed_runtime_evidence
    evidence["review_consumed_runtime_evidence"] = review_client.consumed_runtime_evidence
    ok = evidence["debug_consumed_runtime_evidence"] and evidence["review_consumed_runtime_evidence"]
    summary = _runtime_summary(
        "runtime_evidence_consumption",
        run_id,
        evidence,
        result="debug and review consumed Runtime OS evidence",
    )
    return ok, summary


def _seed_runtime_run(workspace: Path, tasks: list[dict[str, Any]]) -> str:
    from agent_runtime.commands.init_command import InitCommand
    from agent_runtime.storage.json_store import JsonStore
    from agent_runtime.storage.run_store import RunStore
    from agent_runtime.storage.schema_validator import SchemaValidator

    InitCommand(workspace).run()
    validator = SchemaValidator(REPO_ROOT / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(workspace / ".agent", validator)
    run = run_store.create_run("Runtime OS acceptance scenario", goal_id="goal-runtime-os")
    run_id = str(run["run_id"])
    run_store.set_current_session(run_id, "runtime_os_acceptance")
    run_dir = run_store.run_dir(run_id)
    store.write(
        run_dir / "goal_spec.json",
        {
            "schema_version": "0.1.0",
            "goal_id": "goal-runtime-os",
            "original_goal": "Runtime OS acceptance scenario",
            "normalized_goal": "Validate runtime orchestration evidence",
            "goal_type": "codebase_improvement",
            "assumptions": ["deterministic local scenario"],
            "constraints": ["local_first", "no_network"],
            "non_goals": [],
            "expanded_requirements": [],
            "target_outputs": [],
            "definition_of_done": ["Runtime evidence is persisted"],
            "verification_strategy": ["local command"],
            "budget": {"max_iterations": 2, "max_model_calls": 10},
        },
        "goal_spec",
    )
    store.write(run_dir / "task_plan.json", {"schema_version": "0.1.0", "tasks": tasks}, "task_board")
    store.write(
        run_dir / "cost_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "model_calls": 0,
            "tool_calls": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        },
        "cost_report",
    )
    return run_id


def _runtime_task(
    task_id: str,
    title: str,
    *,
    readonly: bool = False,
    write_scope: list[str] | None = None,
    disjoint: bool = False,
) -> dict[str, Any]:
    writes = [] if readonly else list(write_scope or ["out/result.txt"])
    return {
        "schema_version": "0.1.0",
        "task_id": task_id,
        "title": title,
        "description": (
            f"{title} for Runtime OS acceptance, preserving worker evidence, "
            "validation logs, and scoped execution boundaries."
        ),
        "status": "ready",
        "priority": "high",
        "role": "CoderAgent",
        "depends_on": [],
        "acceptance": ["runtime evidence file exists and validation command passes"],
        "allowed_tools": ["run_command"] if readonly else ["write_file", "run_command"],
        "expected_artifacts": writes,
        "task_kind": "research" if readonly else "implementation",
        "expected_changed_files": writes,
        "assigned_agent_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "notes": "Runtime OS acceptance task.",
        "completion_contract": {
            "requires_changed_artifact": bool(writes),
            "requires_verification": True,
            "allows_expected_failure": False,
        },
        "verification_policy": {
            "required": True,
            "allow_expected_failure": False,
            "commands": ["local command"],
        },
        "read_scope": ["AGENTS.md", *writes],
        "write_scope": writes,
        "context_requirements": {
            "mount_type": "coding_context" if writes else "planning_context",
            "include_artifacts": True,
            "include_failures": True,
            "include_decisions": True,
            "include_validation": True,
            "recent_event_count": 20,
        },
        "validation_commands": ["local command"],
        "failure_policy": "create_repair_task",
        "parallel_safety": "disjoint_writes" if disjoint else ("readonly" if readonly else "serial"),
        "merge_strategy": "none",
    }


def _runtime_evidence(run_dir: Path) -> dict[str, Any]:
    return {
        "workers_jsonl": _has_jsonl(run_dir / "workers.jsonl"),
        "worker_results_jsonl": _has_jsonl(run_dir / "worker_results.jsonl"),
        "runtime_profiles_jsonl": _has_jsonl(run_dir / "runtime_profiles.jsonl"),
        "context_mounts_jsonl": _has_jsonl(run_dir / "context_mounts.jsonl"),
        "validation_results_jsonl": _has_jsonl(run_dir / "validation_results.jsonl"),
        "task_execution_evidence_jsonl": _has_jsonl(run_dir / "task_execution_evidence.jsonl"),
    }


def _runtime_summary(
    capability: str,
    run_id: str,
    evidence: dict[str, Any],
    *,
    result: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "runtime_os": {
            "capability": capability,
            "evidence": evidence,
            "result": result,
        },
    }


def _has_jsonl(path: Path) -> bool:
    return path.exists() and any(line.strip() for line in path.read_text(encoding="utf-8").splitlines())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
    return rows
