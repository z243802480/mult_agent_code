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
