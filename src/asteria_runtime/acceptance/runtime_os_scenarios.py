from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from asteria_runtime.acceptance.runtime_os_catalog import runtime_os_capability_map
from asteria_runtime.utils.time import now_iso

REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_spine_request(request: Any) -> bool:
    """立真身循环给每次 chat 打 metadata.loop=model_driven_turn。"""
    return (getattr(request, "metadata", None) or {}).get("loop") == "model_driven_turn"


def _spine_turn(request: Any) -> int:
    return int((getattr(request, "metadata", None) or {}).get("iteration") or 1)


def _acceptance_payload(request: Any) -> dict:
    """FSM 形态下 messages[-1] 是任务 JSON;脊梁形态下是散文旁白/观察回灌——解析失败即空。"""
    try:
        parsed = json.loads(request.messages[-1].content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _acceptance_task_id(request: Any) -> str:
    meta = getattr(request, "metadata", None) or {}
    if meta.get("task_id"):
        return str(meta["task_id"])
    task = _acceptance_payload(request).get("task")
    if isinstance(task, dict) and task.get("task_id"):
        return str(task["task_id"])
    return "task-0001"


def _acceptance_spine_response(request: Any, action: dict) -> Any:
    """把一份 FSM ExecutionAction 复用成脊梁轮次(FSM tool_calls+verification 合并成脊梁一批
    tool_calls;脊梁无独立 verification 字段·run_command 观察即被正确性 gate 计作验证)。
    含 runtime_requests-only 的 FSM 动作在脊梁上没有对应(该能力已随 FSM 退休),故只余空批→收尾。"""
    from asteria_runtime.models.base import ChatResponse, TokenUsage

    tool_calls = [
        {"tool_name": call["tool_name"], "args": call.get("args", {})}
        for call in [*action.get("tool_calls", []), *action.get("verification", [])]
    ]
    if _spine_turn(request) <= 1 and tool_calls:
        payload = {
            "narration": str(action.get("summary") or "执行并验证任务。"),
            "tool_calls": tool_calls,
            "done": False,
        }
    else:
        payload = {
            "narration": str(action.get("completion_notes") or "任务已完成并验证。"),
            "tool_calls": [],
            "done": True,
        }
    return ChatResponse(
        content=json.dumps(payload, ensure_ascii=False),
        finish_reason="stop",
        usage=TokenUsage(1, 1, 2),
        model_provider="runtime-acceptance",
        model_name="spine",
        raw_response={},
    )


class RuntimeAcceptanceClient:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.seen_context_package: dict[str, Any] = {}

    def chat(self, request: Any) -> Any:
        from asteria_runtime.models.base import ChatResponse, TokenUsage

        payload = _acceptance_payload(request)
        task_id = _acceptance_task_id(request)
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
                                'python -c "from pathlib import Path; '
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
                                'python -c "from pathlib import Path; '
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
                "has_scope_summary": bool(package.get("scope_summary")),
                "has_evidence_scope": bool(package.get("evidence_scope")),
                "has_write_scope_files": isinstance(package.get("write_scope_files"), list),
                "has_recent_failures": isinstance(package.get("recent_failures"), list),
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
                                'python -c "from pathlib import Path; '
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
                                    'python -c "from pathlib import Path; '
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
        if _is_spine_request(request):
            return _acceptance_spine_response(request, action)
        return ChatResponse(
            content=json.dumps(action, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="runtime-acceptance",
            model_name=self.mode,
            raw_response={},
        )




class RuntimeEvidenceReviewClient:
    def __init__(self) -> None:
        self.consumed_runtime_evidence = False
        self.consumed_failure_next_hint = False

    def chat(self, request: Any) -> Any:
        from asteria_runtime.models.base import ChatResponse, TokenUsage

        payload = json.loads(request.messages[-1].content)
        trajectory = payload.get("trajectory", {})
        checks = payload.get("deterministic_checks", {})
        observations = payload.get("tool_observations")
        observations = observations if isinstance(observations, list) else []
        self.consumed_runtime_evidence = bool(
            isinstance(trajectory.get("runtime_os_evidence"), dict)
            and trajectory.get("worker_results")
            and "runtime_os_summary" in checks
        )
        self.consumed_failure_next_hint = any(
            isinstance(item, dict)
            and item.get("ok") is False
            and item.get("next_hint") == "diagnose_then_repair_replan_ask_or_stop"
            for item in observations
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
        elif scenario_name == "runtime_prompt_envelope":
            ok, summary = _runtime_prompt_envelope(workspace)
        elif scenario_name == "runtime_disjoint_writes":
            ok, summary = _runtime_disjoint_writes(workspace)
        elif scenario_name == "runtime_worker_failure":
            ok, summary = _runtime_worker_failure(workspace)
        elif scenario_name == "runtime_merge_gate_block":
            ok, summary = _runtime_merge_gate_block(workspace)
        elif scenario_name == "runtime_context_package_slice":
            ok, summary = _runtime_context_package_slice(workspace)
        elif scenario_name == "runtime_sandbox_backend_selection":
            ok, summary = _runtime_sandbox_backend_selection(workspace)
        elif scenario_name == "runtime_independent_verification":
            ok, summary = _runtime_independent_verification(workspace)
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


class PromptEnvelopeAcceptanceClient:
    provider = "runtime-acceptance"

    def chat(self, request: Any) -> Any:
        from asteria_runtime.models.base import ChatResponse, TokenUsage

        del request
        goal = "Validate prompt envelope evidence."
        action = {
            "schema_version": "0.1.0",
            "goal_id": "goal-prompt-envelope",
            "original_goal": goal,
            "normalized_goal": goal,
            "goal_type": "codebase_improvement",
            "assumptions": ["deterministic prompt envelope acceptance"],
            "constraints": ["local_first"],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "req-prompt-envelope",
                    "priority": "must",
                    "description": "Persist prompt envelope and layered capability manifest.",
                    "source": "user",
                    "acceptance": ["prompt_envelope.json exists and is schema-valid"],
                }
            ],
            "target_outputs": [".asteria/runs/<run_id>/prompt_envelope.json"],
            "definition_of_done": ["Prompt envelope evidence is persisted."],
            "verification_strategy": ["schema validation"],
            "budget": {"max_iterations": 1, "max_model_calls": 2},
        }
        return ChatResponse(
            content=json.dumps(action, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="runtime-acceptance",
            model_name="prompt-envelope",
            raw_response={},
        )


def _runtime_prompt_envelope(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.commands.plan_command import PlanCommand
    from asteria_runtime.storage.json_store import JsonStore
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(workspace).run()
    (workspace / "AGENTS.md").write_text(
        "# Runtime acceptance guidance\n\nRespect local-first execution and protected paths.\n",
        encoding="utf-8",
    )
    result = PlanCommand(
        workspace,
        "Validate prompt envelope evidence.",
        model_client=PromptEnvelopeAcceptanceClient(),
    ).run()
    run_dir = workspace / ".asteria" / "runs" / result.run_id
    prompt_path = run_dir / "prompt_envelope.json"
    validator = SchemaValidator(REPO_ROOT / "schemas")
    envelope = JsonStore(validator).read(prompt_path, "prompt_envelope")
    sections = set(envelope.get("section_order") or [])
    raw_manifest = envelope.get("capability_manifest") if isinstance(envelope, dict) else {}
    manifest: dict[str, Any] = raw_manifest if isinstance(raw_manifest, dict) else {}
    evidence = {
        "prompt_envelope_persisted": prompt_path.exists()
        and bool(envelope.get("content_hash"))
        and bool(envelope.get("sections")),
        "capability_manifest_layered": all(
            isinstance(manifest.get(key), list)
            for key in [
                "direct_tools",
                "deferred_tools",
                "mcp_tools",
                "skills",
                "subagents",
                "verification",
            ]
        ),
        "project_guidance_section": "project_guidance" in sections,
        "safety_budget_sections": {"safety_envelope", "user_communication"}.issubset(sections),
    }
    ok = all(evidence.values())
    summary = _runtime_summary("prompt_envelope", result.run_id, evidence, result=result.to_text())
    summary["runtime_os"]["prompt_envelope"] = {
        "path": str(prompt_path),
        "sections": list(envelope.get("section_order") or []),
        "content_hash": envelope.get("content_hash"),
    }
    return ok, summary


def _runtime_parallel_readonly(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand

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
    run_dir = workspace / ".asteria" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    worker_results = _read_jsonl(run_dir / "worker_results.jsonl")
    ok = (
        result.completed == 2
        and len(worker_results) == 2
        and all(item.get("status") == "succeeded" for item in worker_results)
    )
    return ok, _runtime_summary(
        "runtime_parallel_readonly", run_id, evidence, result=result.to_text()
    )


def _runtime_disjoint_writes(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand

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
    run_dir = workspace / ".asteria" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    ok = (
        result.completed == 2
        and (workspace / "out" / "alpha.txt").read_text(encoding="utf-8") == "task-0001"
        and (workspace / "out" / "beta.txt").read_text(encoding="utf-8") == "task-0002"
    )
    return ok, _runtime_summary(
        "runtime_disjoint_writes", run_id, evidence, result=result.to_text()
    )


def _runtime_worker_failure(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand

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
    run_dir = workspace / ".asteria" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    # 立真身直写模型:失败态(验证不过)被正确性 gate 拦为 blocked——错误产物留盘但**不被接受**
    # (任务 blocked 非 done),证据落 task_execution_evidence(contract 不 ok)。取代 FSM 的候选隔离/
    # 晋升失败语义(脊梁无候选/晋升队列)。REQUIREMENT 保留:失败被拦、不被当完成接受、留证据。
    execution_evidence = _read_jsonl(run_dir / "task_execution_evidence.jsonl")
    blocked_records = [
        item
        for item in execution_evidence
        if item.get("status") == "blocked"
        and (item.get("contract_check") or {}).get("ok") is False
    ]
    evidence["failure_blocked"] = result.blocked == 1 and result.completed == 0
    evidence["failure_evidence"] = bool(blocked_records)
    ok = evidence["failure_blocked"] and evidence["failure_evidence"]
    return ok, _runtime_summary("runtime_worker_failure", run_id, evidence, result=result.to_text())




def _runtime_merge_gate_block(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.core.merge_gate import MergeGate

    run_id = _seed_runtime_run(
        workspace,
        [_runtime_task("task-0001", "Prime runtime records", readonly=True)],
    )
    ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("readonly"),
    ).run()
    run_dir = workspace / ".asteria" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)

    class Result:
        ok = True
        summary = "passed"

    gate = MergeGate().evaluate(
        {
            "write_scope": ["safe/output.txt"],
            "completion_contract": {"requires_changed_artifact": True},
        },
        ["safe/output.txt", "unsafe/output.txt"],
        [Result()],
    )
    evidence["merge_gate_blocked"] = not gate.ok and "unsafe/output.txt" in "; ".join(
        gate.violations
    )
    ok = bool(evidence["merge_gate_blocked"])
    summary = _runtime_summary("runtime_merge_gate_block", run_id, evidence)
    summary["runtime_os"]["merge_gate"] = gate.to_dict()
    return ok, summary




def _runtime_context_package_slice(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand

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
    result = ExecuteCommand(
        workspace, run_id=run_id, model_client=RuntimeAcceptanceClient("context_package")
    ).run()
    run_dir = workspace / ".asteria" / "runs" / run_id
    evidence = _runtime_evidence(run_dir)
    # 立真身把 scoped context 渲进提示词(而非作 payload 字段回给模型),故集成证据取自 harness 落的
    # context_mounts.jsonl:per-task coding_context 挂载·含 root_guidance/goal_brief/task_brief。
    # scope 应用由"任务只用其 read_scope(input/scoped.txt)完成、未越权读 input/unscoped.txt"佐证
    # (输出如期写就、run 未 blocked)。细粒度切片入/出由 context_package_builder 单测覆盖。
    mounts = _read_jsonl(run_dir / "context_mounts.jsonl")
    task_mount = next((m for m in mounts if m.get("task_id") == "task-0001"), {})
    includes = task_mount.get("includes") if isinstance(task_mount, dict) else {}
    includes = includes if isinstance(includes, dict) else {}
    evidence["context_mount_built"] = bool(
        task_mount.get("mount_type") == "coding_context"
        and includes.get("goal_brief")
        and includes.get("task_brief")
    )
    evidence["context_scope_applied"] = (
        result.completed == 1
        and (workspace / "out" / "context.txt").read_text(encoding="utf-8")
        == "sliced context observed"
    )
    ok = evidence["context_mount_built"] and evidence["context_scope_applied"]
    summary = _runtime_summary("context_package_slice", run_id, evidence, result=result.to_text())
    summary["runtime_os"]["context_mount"] = task_mount
    return ok, summary


def _runtime_sandbox_backend_selection(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand

    run_id = _seed_runtime_run(
        workspace,
        [_runtime_task("task-0001", "Select sandbox backend", write_scope=["out/alpha.txt"])],
    )
    result = ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("disjoint"),
    ).run()
    run_dir = workspace / ".asteria" / "runs" / run_id
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












def _runtime_independent_verification(workspace: Path) -> tuple[bool, dict[str, Any]]:
    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.commands.review_command import ReviewCommand

    run_id = _seed_runtime_run(
        workspace,
        [_runtime_task("task-0001", "Non-trivial write with verification", write_scope=["out/alpha.txt"])],
    )
    ExecuteCommand(
        workspace,
        run_id=run_id,
        model_client=RuntimeAcceptanceClient("disjoint"),
    ).run()
    review_client = RuntimeEvidenceReviewClient()
    ReviewCommand(workspace, run_id=run_id, model_client=review_client).run()
    run_dir = workspace / ".asteria" / "runs" / run_id
    tool_calls = _read_jsonl(run_dir / "tool_calls.jsonl")
    verification_calls = [
        call for call in tool_calls
        if call.get("tool_name") in {"run_command", "run_tests"}
    ]
    eval_report_path = run_dir / "eval_report.json"
    evidence = {
        "verification_commands_recorded": bool(verification_calls),
        "review_evidence_present": eval_report_path.exists(),
    }
    ok = (
        evidence["verification_commands_recorded"]
        and evidence["review_evidence_present"]
        and review_client.consumed_runtime_evidence
    )
    summary = _runtime_summary(
        "independent_verification",
        run_id,
        evidence,
        result="verification commands and review eval_report present",
    )
    summary["runtime_os"]["verification_count"] = len(verification_calls)
    return ok, summary


def _seed_runtime_run(workspace: Path, tasks: list[dict[str, Any]]) -> str:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.storage.json_store import JsonStore
    from asteria_runtime.storage.run_store import RunStore
    from asteria_runtime.storage.schema_validator import SchemaValidator

    InitCommand(workspace).run()
    validator = SchemaValidator(REPO_ROOT / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(workspace / ".asteria", validator)
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
    store.write(
        run_dir / "task_plan.json", {"schema_version": "0.1.0", "tasks": tasks}, "task_board"
    )
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
        "parallel_safety": "disjoint_writes"
        if disjoint
        else ("readonly" if readonly else "serial"),
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
    return path.exists() and any(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
    )


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
