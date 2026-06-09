from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.agent_loop_decision import persist_runtime_agent_loop_decision
from asteria_runtime.core.agent_loop_executor import persist_agent_loop_execution_result
from asteria_runtime.core.deadline_budget import DeadlineBudget, apply_deadline_budget_env
from asteria_runtime.core.subprocess_heartbeat import run_with_heartbeat
from asteria_runtime.models.model_failure import classify_model_failure
from asteria_runtime.storage.schema_validator import SchemaValidator


DEFAULT_GOAL = "Create a local file hello_runtime.txt containing one line: real model smoke ok"
DEFAULT_EXPECTED_FILE = "hello_runtime.txt"
DEFAULT_EXPECTED_TEXT = "real model smoke ok"
SECRET_ENV_NAMES = {
    "AGENT_MODEL_API_KEY",
    "AGENT_MODEL_STRONG_API_KEY",
    "AGENT_MODEL_MEDIUM_API_KEY",
    "AGENT_MODEL_CHEAP_API_KEY",
}
LOCAL_PROVIDERS = {"local", "ollama", "lmstudio", "vllm", "localai"}
OFFLINE_PROVIDERS = {"fake", "offline"}


@dataclass
class CommandRecord:
    name: str
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass
class SmokeResult:
    workspace: Path
    run_id: str | None
    expected_file: Path
    final_report: Path | None
    transcript: Path
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    commands: list[CommandRecord] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        ended_at = self.ended_at if self.ended_at is not None else time.monotonic()
        return {
            "workspace": str(self.workspace),
            "run_id": self.run_id,
            "expected_file": str(self.expected_file),
            "final_report": str(self.final_report) if self.final_report else None,
            "transcript": str(self.transcript),
            "duration_seconds": round(ended_at - self.started_at, 3),
            "diagnostics": self.diagnostics,
            "commands": [record.to_dict() for record in self.commands],
        }


class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeCase:
    name: str
    task_kind: str
    route: str
    reason: str
    goal: str
    expected_file: str
    expected_text: str
    max_iterations: int = 3
    max_tasks_per_iteration: int = 1
    setup_files: dict[str, str] = field(default_factory=dict)


P0_MATRIX_CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        name="file_output",
        task_kind="file_output",
        route="artifact_creation",
        reason="Verifies a bounded goal can produce a concrete file artifact.",
        goal=(
            "Create a local file p0_matrix_file_output.txt containing one line: "
            "P0 matrix file output ok"
        ),
        expected_file="p0_matrix_file_output.txt",
        expected_text="P0 matrix file output ok",
    ),
    SmokeCase(
        name="single_file_bugfix",
        task_kind="bug_fix",
        route="repair",
        reason="Verifies a focused single-file defect can be repaired and validated.",
        goal=(
            "Fix calc.py so add(2, 3) returns 5. Keep the change limited to calc.py "
            "and preserve the existing test intent."
        ),
        expected_file="calc.py",
        expected_text="return a + b",
        max_iterations=5,
        setup_files={
            "calc.py": "def add(a, b):\n    return a - b\n",
            "test_calc.py": (
                "from calc import add\n\n"
                "def test_add():\n"
                "    assert add(2, 3) == 5\n"
            ),
        },
    ),
    SmokeCase(
        name="doc_update",
        task_kind="doc_update",
        route="artifact_creation",
        reason="Verifies documentation-only tasks create durable user-facing artifacts.",
        goal=(
            "Create docs/p0_matrix_doc_update.md with the heading P0 Matrix Doc Update "
            "and a short checklist for reviewing real-provider smoke evidence."
        ),
        expected_file="docs/p0_matrix_doc_update.md",
        expected_text="P0 Matrix Doc Update",
    ),
    SmokeCase(
        name="context_maintenance",
        task_kind="doc_update",
        route="context_slimming",
        reason=(
            "Verifies a bounded maintenance task can read several local context files "
            "and produce a concise durable summary."
        ),
        goal=(
            "Read docs/route_notes.md, docs/context_notes.md, and docs/capability_notes.md. "
            "Create docs/context_maintenance_summary.md with heading Context Maintenance Summary "
            "and three bullet sections named Route, Context, and Capability. Keep it concise "
            "and preserve the phrase real provider subsets."
        ),
        expected_file="docs/context_maintenance_summary.md",
        expected_text="Context Maintenance Summary",
        setup_files={
            "docs/route_notes.md": (
                "# Route Notes\n\n"
                "- Low-risk documentation and simple file tasks should prefer medium routes.\n"
                "- Strong routes are reserved for release gates, high-risk architecture review, "
                "and difficult repair.\n"
                "- Provider matrix results should record purpose, tier, latency, context mode, "
                "and repair count.\n"
            ),
            "docs/context_notes.md": (
                "# Context Notes\n\n"
                "- Fast path task execution should mount slim context for documentation-only "
                "artifact creation.\n"
                "- Focused context is appropriate for single-file bug fixes where target files "
                "are known.\n"
                "- Context compaction should preserve evidence refs and next actions before "
                "long pauses.\n"
            ),
            "docs/capability_notes.md": (
                "# Capability Notes\n\n"
                "- Fake/offline suites are used for quick main-path health checks.\n"
                "- real provider subsets calibrate latency and output quality after fake "
                "health passes.\n"
                "- A provider run should avoid unnecessary strong model calls on low-risk "
                "fast paths.\n"
            ),
        },
    ),
    SmokeCase(
        name="contract_mismatch_replan",
        task_kind="contract_mismatch",
        route="replan",
        reason=(
            "Exercises the route where an implementation contract mismatch should cause "
            "a bounded replan rather than blind repair."
        ),
        goal=(
            "If the requested artifact contract is ambiguous, replan once and then create "
            "docs/p0_matrix_contract_mismatch_replan.md containing: contract mismatch replan ok"
        ),
        expected_file="docs/p0_matrix_contract_mismatch_replan.md",
        expected_text="contract mismatch replan ok",
        max_iterations=5,
    ),
    SmokeCase(
        name="verification_failure_repair",
        task_kind="verification_failure",
        route="repair",
        reason=(
            "Exercises the route where failing verification should trigger a bounded repair "
            "before final review."
        ),
        goal=(
            "Run the provided test and repair repair_target.py so status() returns 'fixed'. "
            "Keep the repair minimal."
        ),
        expected_file="repair_target.py",
        expected_text="return 'fixed'",
        max_iterations=5,
        setup_files={
            "repair_target.py": "def status():\n    return 'broken'\n",
            "test_repair_target.py": (
                "from repair_target import status\n\n"
                "def test_status():\n"
                "    assert status() == 'fixed'\n"
            ),
        },
    ),
)

MATRIX_PRESETS: dict[str, tuple[str, ...]] = {
    "rolling-fastpath-v1": (
        "doc_update",
        "single_file_bugfix",
        "context_maintenance",
    ),
}


def matrix_cases(matrix: str, selected_names: list[str] | None = None) -> list[SmokeCase]:
    if matrix != "p0":
        raise SmokeFailure(f"Unsupported smoke matrix: {matrix}")
    cases = list(P0_MATRIX_CASES)
    if not selected_names:
        return cases
    known = {case.name: case for case in cases}
    unknown = [name for name in selected_names if name not in known]
    if unknown:
        raise SmokeFailure(
            "Unknown matrix case(s): "
            + ", ".join(unknown)
            + ". Known: "
            + ", ".join(sorted(known))
        )
    return [known[name] for name in selected_names]


def matrix_preset_case_names(preset: str | None) -> list[str]:
    if not preset:
        return []
    if preset not in MATRIX_PRESETS:
        raise SmokeFailure(
            "Unknown matrix preset: "
            + preset
            + ". Known: "
            + ", ".join(sorted(MATRIX_PRESETS))
        )
    return list(MATRIX_PRESETS[preset])


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_from_args(args)


def run_from_args(args: argparse.Namespace) -> None:
    result: SmokeResult | None = None
    cleanup = False
    fake_provider_names = [
        "AGENT_MODEL_PROVIDER",
        "AGENT_MODEL_STRONG_PROVIDER",
        "AGENT_MODEL_MEDIUM_PROVIDER",
        "AGENT_MODEL_CHEAP_PROVIDER",
    ]
    previous_providers = {name: os.environ.get(name) for name in fake_provider_names}
    try:
        if args.allow_fake:
            for name in fake_provider_names:
                os.environ[name] = "fake"
        validate_environment(allow_fake=args.allow_fake)
        timeout_budget = DeadlineBudget.for_smoke(
            args.command_timeout_seconds,
            model_max_retries=args.model_max_retries,
        )
        os.environ.setdefault(
            "AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES",
            str(args.model_max_retries),
        )
        apply_deadline_budget_env(os.environ, timeout_budget)
        if getattr(args, "matrix_preset", None) and not getattr(args, "matrix", None):
            args.matrix = "p0"
        if getattr(args, "matrix", None):
            run_matrix_from_args(args, timeout_budget=timeout_budget)
            return
        result, cleanup = prepare_single_result(args)
        run_smoke(args, result)
        result.ended_at = time.monotonic()
        write_transcript(result)
        if args.summary_json:
            write_json(args.summary_json, result.summary())
        print_success(result)
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic script boundary
        if result:
            result.ended_at = time.monotonic()
        if result:
            write_transcript(result)
            if args.summary_json:
                write_json(args.summary_json, result.summary())
            print_failure(exc, result)
        else:
            print(f"Real model smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        if args.allow_fake:
            for name, value in previous_providers.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        if cleanup and args.cleanup and result and result.workspace.exists():
            shutil.rmtree(result.workspace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a real model end-to-end smoke test in an isolated workspace."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Workspace root. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--goal",
        default=DEFAULT_GOAL,
        help="Goal passed to asteria /run.",
    )
    parser.add_argument(
        "--expected-file",
        default=DEFAULT_EXPECTED_FILE,
        help="Expected artifact path relative to the workspace.",
    )
    parser.add_argument(
        "--expected-text",
        default=DEFAULT_EXPECTED_TEXT,
        help="Text expected inside the artifact.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum /run loop iterations.",
    )
    parser.add_argument(
        "--max-tasks-per-iteration",
        type=int,
        default=1,
        help="Maximum tasks executed per iteration.",
    )
    parser.add_argument(
        "--run-attempts",
        type=int,
        default=2,
        help="Maximum attempts for the full /run command when provider transport fails early.",
    )
    parser.add_argument(
        "--model-max-retries",
        type=int,
        default=1,
        help="AGENT_MODEL_MAX_RETRIES value used inside smoke subprocesses when unset.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=900,
        help="Maximum seconds for each asteria_runtime subprocess.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run asteria_runtime.",
    )
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow AGENT_MODEL_PROVIDER=fake/offline. Intended for CI coverage of this script.",
    )
    parser.add_argument(
        "--no-recovery",
        action="store_true",
        help="Do not attempt review/resume recovery after a failed /run.",
    )
    parser.add_argument(
        "--recovery-rounds",
        type=int,
        default=2,
        help="Maximum bounded review/decision/resume recovery rounds.",
    )
    parser.add_argument(
        "--no-research",
        action="store_true",
        help="Skip /run pre-planning research for clear smoke goals.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the temporary workspace after a successful run.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional path for a machine-readable smoke or matrix summary.",
    )
    parser.add_argument(
        "--matrix",
        choices=["p0"],
        default=None,
        help="Run a curated smoke matrix instead of a single smoke goal.",
    )
    parser.add_argument(
        "--matrix-preset",
        choices=sorted(MATRIX_PRESETS),
        default=None,
        help="Run a named smoke matrix subset, for example rolling-fastpath-v1.",
    )
    parser.add_argument(
        "--matrix-case",
        action="append",
        default=[],
        help="Limit --matrix to one case name; may be repeated.",
    )
    parser.add_argument(
        "--matrix-output-dir",
        type=Path,
        default=None,
        help="Directory for matrix case workspaces and matrix_summary.json.",
    )
    return parser


def validate_environment(*, allow_fake: bool) -> None:
    provider = os.getenv("AGENT_MODEL_PROVIDER", "minimax").lower()
    if provider in OFFLINE_PROVIDERS and not allow_fake:
        raise SmokeFailure(
            "AGENT_MODEL_PROVIDER is offline/fake. Use --allow-fake only for script tests."
        )
    if provider not in LOCAL_PROVIDERS | OFFLINE_PROVIDERS:
        if not os.getenv("AGENT_MODEL_API_KEY") and not os.getenv("AGENT_MODEL_STRONG_API_KEY"):
            raise SmokeFailure(
                "AGENT_MODEL_API_KEY or AGENT_MODEL_STRONG_API_KEY is required for real providers."
            )


def prepare_workspace(root: Path | None) -> tuple[Path, bool]:
    if root is not None:
        workspace = root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, False
    return Path(tempfile.mkdtemp(prefix="agent-real-e2e-")).resolve(), True


def run_single_from_args(
    args: argparse.Namespace,
    *,
    timeout_budget: DeadlineBudget,
    case: SmokeCase | None = None,
) -> tuple[SmokeResult, bool]:
    result, cleanup = prepare_single_result(args, case=case)
    run_smoke(args, result)
    result.ended_at = time.monotonic()
    write_transcript(result)
    return result, cleanup


def prepare_single_result(
    args: argparse.Namespace,
    *,
    case: SmokeCase | None = None,
) -> tuple[SmokeResult, bool]:
    workspace, cleanup = prepare_workspace(args.root)
    if case:
        apply_setup_files(workspace, case.setup_files)
    timeout_budget = DeadlineBudget.for_smoke(
        args.command_timeout_seconds,
        model_max_retries=args.model_max_retries,
    )
    return (
        SmokeResult(
            workspace=workspace,
            run_id=None,
            expected_file=workspace / args.expected_file,
            final_report=None,
            transcript=workspace / "real_model_smoke_transcript.json",
            diagnostics={"timeout_budget": timeout_budget.as_dict()},
        ),
        cleanup,
    )


def run_matrix_from_args(args: argparse.Namespace, *, timeout_budget: DeadlineBudget) -> None:
    selected_names = [
        *matrix_preset_case_names(getattr(args, "matrix_preset", None)),
        *list(getattr(args, "matrix_case", []) or []),
    ]
    cases = matrix_cases(str(args.matrix), selected_names)
    output_dir = matrix_output_dir(args)
    workspaces_dir = output_dir / "workspaces"
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    case_summaries: list[dict[str, Any]] = []
    for case in cases:
        case_args = argparse.Namespace(**vars(args))
        case_workspace = workspaces_dir / case.name
        case_args.root = case_workspace
        case_args.goal = case.goal
        case_args.expected_file = case.expected_file
        case_args.expected_text = case.expected_text
        case_args.max_iterations = case.max_iterations
        case_args.max_tasks_per_iteration = case.max_tasks_per_iteration
        case_args.summary_json = output_dir / f"{case.name}_summary.json"
        case_args.matrix = None
        try:
            result, _cleanup = run_single_from_args(
                case_args,
                timeout_budget=timeout_budget,
                case=case,
            )
            write_json(case_args.summary_json, result.summary())
            case_summaries.append(
                matrix_case_summary(case, result=result, summary_json=case_args.summary_json)
            )
        except Exception as exc:  # noqa: BLE001 - keep collecting bounded matrix evidence
            case_summaries.append(
                matrix_case_summary(
                    case,
                    workspace=case_workspace,
                    summary_json=case_args.summary_json,
                    failure=exc,
                )
            )
    summary = {
        "schema_version": "0.1.0",
        "matrix": args.matrix,
        "matrix_preset": getattr(args, "matrix_preset", None),
        "provider_mode": "fake" if args.allow_fake else "real",
        "created_at": datetime.now(UTC).isoformat(),
        "ok": all(item["ok"] for item in case_summaries),
        "output_dir": str(output_dir),
        "case_count": len(case_summaries),
        "passed": sum(1 for item in case_summaries if item["ok"]),
        "failed": sum(1 for item in case_summaries if not item["ok"]),
        "duration_seconds": round(time.monotonic() - started, 3),
        "cases": case_summaries,
    }
    matrix_summary_path = output_dir / "matrix_summary.json"
    write_matrix_summary_json(matrix_summary_path, summary)
    if args.summary_json:
        write_matrix_summary_json(args.summary_json, summary)
    print_matrix_summary(summary, matrix_summary_path)
    if not summary["ok"]:
        raise SmokeFailure("real-model smoke matrix failed; see matrix_summary.json for details.")


def matrix_output_dir(args: argparse.Namespace) -> Path:
    if args.matrix_output_dir is not None:
        return args.matrix_output_dir.resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if args.root is not None:
        return (
            args.root.resolve()
            / ".asteria"
            / "verification"
            / "real_provider_matrix"
            / stamp
        )
    return Path(tempfile.mkdtemp(prefix="asteria-real-provider-matrix-")).resolve()


def apply_setup_files(workspace: Path, setup_files: dict[str, str]) -> None:
    for relative_path, content in setup_files.items():
        target = (workspace / relative_path).resolve()
        if not str(target).startswith(str(workspace.resolve())):
            raise SmokeFailure(f"Setup file escapes workspace: {relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def matrix_case_summary(
    case: SmokeCase,
    *,
    result: SmokeResult | None = None,
    workspace: Path | None = None,
    summary_json: Path,
    failure: Exception | None = None,
) -> dict[str, Any]:
    case_workspace = result.workspace if result else workspace
    evidence_refs = []
    if result:
        evidence_refs.extend([str(result.transcript), str(summary_json)])
        if result.final_report:
            evidence_refs.append(str(result.final_report))
    agent_loop = matrix_agent_loop_summary(result, workspace=case_workspace)
    context_strategy = matrix_context_strategy_summary(result, workspace=case_workspace)
    return {
        "name": case.name,
        "task_kind": case.task_kind,
        "route": case.route,
        "reason": case.reason,
        "ok": failure is None,
        "workspace": str(case_workspace) if case_workspace else None,
        "summary_json": str(summary_json),
        "expected_file": case.expected_file,
        "expected_text": case.expected_text,
        "run_id": result.run_id if result else None,
        "final_report": str(result.final_report) if result and result.final_report else None,
        "diagnostics": result.diagnostics if result else {},
        "agent_loop": agent_loop,
        "context_strategy": context_strategy,
        "failure_type": type(failure).__name__ if failure else None,
        "failure_summary": redact(str(failure)) if failure else None,
        "evidence_refs": evidence_refs,
    }


def matrix_context_strategy_summary(
    result: SmokeResult | None,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    resolved_workspace = result.workspace if result is not None else workspace
    run_id = result.run_id if result is not None else None
    if resolved_workspace is not None and not run_id:
        run_id = current_run_id(resolved_workspace)
    if resolved_workspace is None or not run_id:
        return {}
    path = resolved_workspace / ".asteria" / "runs" / run_id / "model_calls.jsonl"
    if not path.exists():
        return {"status": "missing", "model_calls_path": str(path)}
    try:
        calls = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as exc:
        return {
            "status": "unreadable",
            "model_calls_path": str(path),
            "failure_summary": redact(str(exc)),
        }
    context_modes: dict[str, int] = {}
    fast_path_kinds: dict[str, int] = {}
    purpose_context_modes: dict[str, dict[str, int]] = {}
    context_tokens: list[int] = []
    model_tiers: dict[str, int] = {}
    purposes: dict[str, int] = {}
    failed_model_call_types: dict[str, int] = {}
    failed_calls = 0
    for call in calls:
        if not isinstance(call, dict):
            continue
        context_mode = str(call.get("context_mode") or "unknown")
        fast_path_kind = str(call.get("fast_path_task_kind") or "unknown")
        purpose = str(call.get("purpose") or "unknown")
        tier = str(call.get("model_tier") or "unknown")
        context_modes[context_mode] = context_modes.get(context_mode, 0) + 1
        fast_path_kinds[fast_path_kind] = fast_path_kinds.get(fast_path_kind, 0) + 1
        model_tiers[tier] = model_tiers.get(tier, 0) + 1
        purposes[purpose] = purposes.get(purpose, 0) + 1
        if str(call.get("status") or "") == "failure":
            failed_calls += 1
            failure_type = _model_call_failure_type(call)
            failed_model_call_types[failure_type] = (
                failed_model_call_types.get(failure_type, 0) + 1
            )
        by_mode = purpose_context_modes.setdefault(purpose, {})
        by_mode[context_mode] = by_mode.get(context_mode, 0) + 1
        estimate = call.get("context_estimate")
        estimate = estimate if isinstance(estimate, dict) else {}
        estimated_tokens = estimate.get("estimated_tokens")
        if not isinstance(estimated_tokens, int):
            estimated_tokens = estimate.get("total_tokens")
        if isinstance(estimated_tokens, int):
            context_tokens.append(estimated_tokens)
    known_modes = sum(count for mode, count in context_modes.items() if mode != "unknown")
    slim_calls = context_modes.get("slim", 0)
    total_calls = len([call for call in calls if isinstance(call, dict)])
    return {
        "status": "recorded",
        "model_calls_path": str(path),
        "model_call_count": total_calls,
        "context_modes": dict(sorted(context_modes.items())),
        "fast_path_task_kinds": dict(sorted(fast_path_kinds.items())),
        "model_tiers": dict(sorted(model_tiers.items())),
        "purposes": dict(sorted(purposes.items())),
        "purpose_context_modes": {
            purpose: dict(sorted(modes.items()))
            for purpose, modes in sorted(purpose_context_modes.items())
        },
        "context_mode_recorded": known_modes,
        "slim_model_calls": slim_calls,
        "strong_model_calls": model_tiers.get("strong", 0),
        "failed_model_calls": failed_calls,
        "failed_model_call_types": dict(sorted(failed_model_call_types.items())),
        "task_execution_model_calls": purposes.get("task_execution", 0),
        "task_repair_model_calls": purposes.get("task_repair", 0),
        "run_review_model_calls": purposes.get("run_review", 0),
        "average_context_estimated_tokens": (
            sum(context_tokens) / len(context_tokens) if context_tokens else None
        ),
        "max_context_estimated_tokens": max(context_tokens) if context_tokens else None,
    }


def _model_call_failure_type(call: dict[str, Any]) -> str:
    streaming = call.get("streaming")
    streaming = streaming if isinstance(streaming, dict) else {}
    text = "\n".join(
        [
            str(call.get("summary") or ""),
            str(streaming.get("error_type") or ""),
            str(streaming.get("mode") or ""),
        ]
    )
    return classify_model_failure(text)


def matrix_agent_loop_summary(
    result: SmokeResult | None,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    resolved_workspace = result.workspace if result is not None else workspace
    run_id = result.run_id if result is not None else None
    if resolved_workspace is not None and not run_id:
        run_id = current_run_id(resolved_workspace)
    if resolved_workspace is None or not run_id:
        return {}
    run_dir = resolved_workspace / ".asteria" / "runs" / run_id
    path = run_dir / "agent_loop_run_summary.json"
    source = "agent_loop_run_summary"
    if not path.exists():
        run_loop_path = run_dir / "run_loop_summary.json"
        if not run_loop_path.exists():
            return {"status": "missing", "summary_path": str(path)}
        path = run_loop_path
        source = "run_loop_summary"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "status": "unreadable",
            "summary_path": str(path),
            "failure_summary": redact(str(exc)),
        }
    budget = summary.get("budget") if isinstance(summary.get("budget"), dict) else {}
    context_pressure = (
        summary.get("context_pressure")
        if isinstance(summary.get("context_pressure"), dict)
        else {}
    )
    recovery_chain = (
        summary.get("recovery_chain") if isinstance(summary.get("recovery_chain"), dict) else {}
    )
    if source == "run_loop_summary":
        runtime_progress = (
            summary.get("runtime_progress")
            if isinstance(summary.get("runtime_progress"), dict)
            else {}
        )
        loop = runtime_progress.get("loop") if isinstance(runtime_progress.get("loop"), dict) else {}
        tool_use = (
            runtime_progress.get("tool_use")
            if isinstance(runtime_progress.get("tool_use"), dict)
            else {}
        )
        latest_decision = (
            loop.get("latest_decision")
            if isinstance(loop.get("latest_decision"), dict)
            else {}
        )
        budget = loop.get("budget") if isinstance(loop.get("budget"), dict) else {}
        context_pressure = (
            loop.get("context_pressure")
            if isinstance(loop.get("context_pressure"), dict)
            else {}
        )
        recovery = loop.get("recovery") if isinstance(loop.get("recovery"), dict) else {}
        return {
            "status": "run_loop_recorded",
            "summary_path": str(path),
            "source": source,
            "exit_reason": summary.get("stop_reason"),
            "recommended_command": summary.get("recommended_next_command"),
            "latest_action": tool_use.get("action") or latest_decision.get("action"),
            "rounds_completed": loop.get("rounds_completed"),
            "max_rounds": loop.get("max_rounds"),
            "budget_status": budget.get("status"),
            "budget_highest_label": budget.get("highest_label"),
            "budget_model_calls": budget.get("model_calls"),
            "budget_tool_calls": budget.get("tool_budget_units"),
            "budget_repair_attempts": budget.get("repair_attempts"),
            "context_pressure_status": context_pressure.get("status"),
            "context_window_ratio": context_pressure.get("context_window_ratio"),
            "recovery_required": recovery.get("required"),
            "recovery_satisfied": recovery.get("satisfied"),
        }
    return {
        "status": "recorded",
        "summary_path": str(path),
        "source": source,
        "exit_reason": summary.get("exit_reason"),
        "recommended_command": summary.get("recommended_command"),
        "latest_action": summary.get("latest_action"),
        "rounds_completed": summary.get("rounds_completed"),
        "max_rounds": summary.get("max_rounds"),
        "budget_status": budget.get("status"),
        "budget_highest_label": budget.get("highest_label"),
        "budget_model_calls": budget.get("model_calls"),
        "budget_tool_calls": budget.get("tool_calls"),
        "budget_repair_attempts": budget.get("repair_attempts"),
        "context_pressure_status": context_pressure.get("status"),
        "context_window_ratio": context_pressure.get("context_window_ratio"),
        "recovery_required": recovery_chain.get("required"),
        "recovery_satisfied": recovery_chain.get("satisfied"),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_matrix_summary_json(path: Path, payload: dict[str, Any]) -> None:
    SchemaValidator(Path(__file__).resolve().parents[2] / "schemas").validate(
        "real_provider_matrix_summary",
        payload,
    )
    write_json(path, payload)


def run_already_completed_successfully(workspace: Path, run_id: str) -> bool:
    run_dir = workspace / ".asteria" / "runs" / run_id
    run_path = run_dir / "run.json"
    if not run_path.exists():
        return False
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("status") != "completed":
        return False
    task_plan_path = run_dir / "task_plan.json"
    if not task_plan_path.exists():
        return True
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    unfinished = [
        task
        for task in task_plan.get("tasks", [])
        if isinstance(task, dict) and task.get("status") not in {"done", "discarded"}
    ]
    return not unfinished


def run_smoke(args: argparse.Namespace, result: SmokeResult) -> None:
    workspace = result.workspace
    run_command(result, args.python, "/init", "--root", str(workspace), name="init")
    run_command(
        result,
        args.python,
        "/model-check",
        "--root",
        str(workspace),
        name="model-check",
    )
    run = run_agent_run_with_retries(args, result)
    result.run_id = current_run_id(workspace)
    if run.returncode != 0:
        if is_transient_provider_failure(run) and result.run_id:
            try:
                result.final_report = validate_artifacts(
                    workspace,
                    result.run_id,
                    result=result,
                    expected_file=result.expected_file,
                    expected_text=args.expected_text,
                )
                result.diagnostics["accepted_transient_run_failure"] = True
                return
            except SmokeFailure:
                pass
        raise SmokeFailure("asteria /run failed; see transcript for command output.")

    if (
        not args.no_recovery
        and result.run_id
        and (workspace / ".asteria" / "runs" / result.run_id / "goal_spec.json").exists()
        and not (workspace / ".asteria" / "runs" / result.run_id / "eval_report.json").exists()
        and not run_already_completed_successfully(workspace, result.run_id)
    ):
        run_command(
            result,
            args.python,
            "/review",
            "--root",
            str(workspace),
            "--session-id",
            result.run_id,
            name="recovery-review",
            check=False,
            timeout_seconds=review_timeout_seconds(),
        )
        recover_run(args, result)

    result.run_id = result.run_id or current_run_id(workspace)
    result.final_report = validate_artifacts(
        workspace,
        result.run_id,
        result=result,
        expected_file=result.expected_file,
        expected_text=args.expected_text,
    )


def run_agent_run_with_retries(args: argparse.Namespace, result: SmokeResult) -> CommandRecord:
    last_record: CommandRecord | None = None
    attempts = max(1, int(args.run_attempts))
    run_args = [
        "/run",
        args.goal,
        "--root",
        str(result.workspace),
        "--max-iterations",
        str(args.max_iterations),
        "--max-tasks-per-iteration",
        str(args.max_tasks_per_iteration),
    ]
    if args.no_research:
        run_args.append("--no-research")
    for attempt in range(1, attempts + 1):
        name = "run" if attempt == 1 else f"run-retry-{attempt}"
        record = run_command(
            result,
            args.python,
            *run_args,
            name=name,
            check=False,
        )
        last_record = record
        if record.returncode == 0:
            return record
        if attempt >= attempts or not is_transient_provider_failure(record):
            return record
    if last_record is None:
        raise SmokeFailure("asteria /run did not execute.")
    return last_record


def resolve_pending_decisions(args: argparse.Namespace, result: SmokeResult) -> None:
    if not result.run_id:
        return
    for decision in pending_decisions(result.workspace, result.run_id):
        decision_id = str(decision["decision_id"])
        option_id = recovery_option_id(decision)
        option_args = ["--select-option-id", option_id] if option_id else ["--use-default"]
        record = run_command(
            result,
            args.python,
            "/decide",
            "--root",
            str(result.workspace),
            "--session-id",
            result.run_id,
            "--decision-id",
            decision_id,
            *option_args,
            name=f"recovery-decide-{decision_id}",
            check=False,
        )
        if record.returncode != 0:
            if (
                is_budget_guard_decision(decision)
                and "user_decisions exceeded budget" in record.stderr
            ):
                return
            raise SmokeFailure(f"{record.name} failed with exit code {record.returncode}.")


def recover_run(args: argparse.Namespace, result: SmokeResult) -> None:
    if not result.run_id:
        return
    for round_index in range(1, max(1, int(args.recovery_rounds)) + 1):
        resolve_pending_decisions(args, result)
        record = run_command(
            result,
            args.python,
            "/resume",
            "--root",
            str(result.workspace),
            "--session-id",
            result.run_id,
            "--max-iterations",
            str(args.max_iterations),
            "--max-tasks-per-iteration",
            str(args.max_tasks_per_iteration),
            name="recovery-resume" if round_index == 1 else f"recovery-resume-{round_index}",
        )
        if "Status: completed" in record.stdout:
            return
        if not pending_decision_ids(result.workspace, result.run_id):
            break
    run_command(
        result,
        args.python,
        "/review",
        "--root",
        str(result.workspace),
        "--session-id",
        result.run_id,
        name="recovery-review-final",
        check=False,
        timeout_seconds=review_timeout_seconds(),
    )


def recovery_option_id(decision: dict[str, Any]) -> str | None:
    raw_metadata = decision.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    option_ids = {
        str(option.get("option_id"))
        for option in decision.get("options", [])
        if isinstance(option, dict) and option.get("option_id")
    }
    if metadata.get("kind") == "budget_guard" and "continue_once" in option_ids:
        return "continue_once"
    if metadata.get("kind") == "execution_policy_approval" and "approve_once" in option_ids:
        return "approve_once"
    return None


def is_budget_guard_decision(decision: dict[str, Any]) -> bool:
    raw_metadata = decision.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return metadata.get("kind") == "budget_guard"


def pending_decision_ids(workspace: Path, run_id: str) -> list[str]:
    return [str(decision["decision_id"]) for decision in pending_decisions(workspace, run_id)]


def pending_decisions(workspace: Path, run_id: str) -> list[dict[str, Any]]:
    path = workspace / ".asteria" / "runs" / run_id / "decisions.jsonl"
    if not path.exists():
        return []
    decisions: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decision = json.loads(line)
        if decision.get("status") == "pending" and decision.get("decision_id"):
            decisions.append(decision)
    return decisions


def is_transient_provider_failure(record: CommandRecord) -> bool:
    text = f"{record.stdout}\n{record.stderr}".lower()
    transient_markers = [
        "unexpected_eof",
        "eof occurred in violation of protocol",
        "tls",
        "remote end closed connection",
        "connection closed",
        "connection reset",
        "timeout",
        "timed out",
        "deadline exceeded",
        "temporarily unavailable",
        "too many requests",
        "429",
        "500",
        "502",
        "503",
        "504",
        "urlopen error",
    ]
    return any(marker in text for marker in transient_markers)


def run_command(
    result: SmokeResult,
    python: str,
    *args: str,
    name: str,
    check: bool = True,
    timeout_seconds: int | None = None,
) -> CommandRecord:
    env = os.environ.copy()
    source_root = source_checkout_root()
    if source_root is not None:
        env["PYTHONPATH"] = merge_pythonpath(str(source_root), env.get("PYTHONPATH"))
    env.setdefault("AGENT_MODEL_MAX_RETRIES", str(args_model_max_retries()))
    timeout = timeout_seconds or int(os.getenv("AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS", "900"))
    try:
        completed = run_with_heartbeat(
            [python, "-m", "asteria_runtime", *args],
            cwd=result.workspace,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            label=name,
            progress_root=result.workspace,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = text_or_empty(exc.stdout)
        stderr = text_or_empty(exc.stderr) + f"\nCommand timed out after {timeout}s."
        record = CommandRecord(
            name=name,
            command=["python", "-m", "asteria_runtime", *args],
            returncode=None,
            stdout=redact(stdout),
            stderr=redact(stderr),
        )
        result.commands.append(record)
        record_recovery_loop_decision(result, record, reason=f"{name} timed out after {timeout}s.")
        if check:
            raise SmokeFailure(f"{name} timed out after {timeout}s.")
        return record
    record = CommandRecord(
        name=name,
        command=["python", "-m", "asteria_runtime", *args],
        returncode=completed.returncode,
        stdout=redact(completed.stdout),
        stderr=redact(completed.stderr),
    )
    result.commands.append(record)
    if completed.returncode != 0:
        record_recovery_loop_decision(
            result,
            record,
            reason=f"{name} failed with exit code {completed.returncode}.",
        )
    if check and completed.returncode != 0:
        raise SmokeFailure(f"{name} failed with exit code {completed.returncode}.")
    return record


def record_recovery_loop_decision(
    result: SmokeResult,
    record: CommandRecord,
    *,
    reason: str,
) -> None:
    if not result.run_id or not _is_review_or_recovery_command(record.name):
        return
    run_dir = result.workspace / ".asteria" / "runs" / result.run_id
    if not run_dir.exists():
        return
    text = f"{record.stdout}\n{record.stderr}\n{reason}".lower()
    action = "repair"
    if "decision" in text or "permission" in text or "budget" in text:
        action = "ask"
    elif "plan" in text or "scope" in text:
        action = "replan"
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    decision = persist_runtime_agent_loop_decision(
        run_dir=run_dir,
        validator=validator,
        run_id=result.run_id,
        task_id=latest_task_id(run_dir),
        action=action,
        reason=(
            "Recovery command failed before a model-authored next action was available: "
            f"{reason}"
        ),
        capability_name=record.name,
        expected_observation={
            "summary": "Review or recovery failure is captured as a loop decision.",
            "success_signal": "The next runtime command can continue through debug, replan, decide, or stop.",
            "command": record.name,
        },
        risk="medium",
        evidence_refs=[str(run_dir / "user_progress.jsonl"), str(run_dir / "model_calls.jsonl")],
        budget_hint={"model_calls": 1, "tool_budget_units": 0, "context": "recovery_failure"},
    )
    if decision is not None:
        persist_agent_loop_execution_result(
            run_dir=run_dir,
            validator=validator,
            decision=decision,
            create_decision_point=action == "ask",
        )


def _is_review_or_recovery_command(name: str) -> bool:
    return name in {"run", "review"} or name.startswith("run-retry-") or name.startswith("recovery-")


def latest_task_id(run_dir: Path) -> str | None:
    task_plan_path = run_dir / "task_plan.json"
    if not task_plan_path.exists():
        return None
    try:
        task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tasks = task_plan.get("tasks") if isinstance(task_plan, dict) else None
    if not isinstance(tasks, list):
        return None
    for task in reversed(tasks):
        if isinstance(task, dict) and task.get("task_id"):
            return str(task["task_id"])
    return None


def args_model_max_retries() -> int:
    return int(os.getenv("AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES", "1"))


def review_timeout_seconds() -> int:
    return int(os.getenv("AGENT_MODEL_SMOKE_REVIEW_TIMEOUT_SECONDS", "180"))


def merge_pythonpath(src_path: str, current: str | None) -> str:
    if not current:
        return src_path
    paths = current.split(os.pathsep)
    if src_path in paths:
        return current
    return os.pathsep.join([src_path, current])


def source_checkout_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2] / "src"
    return candidate if (candidate / "asteria_runtime").is_dir() else None


def current_run_id(workspace: Path) -> str | None:
    current_path = workspace / ".asteria" / "current_session.json"
    if current_path.exists():
        current = json.loads(current_path.read_text(encoding="utf-8"))
        return str(current["session_id"])
    runs_dir = workspace / ".asteria" / "runs"
    if not runs_dir.exists():
        return None
    runs = sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
    return runs[-1] if runs else None


def validate_artifacts(
    workspace: Path,
    run_id: str | None,
    *,
    result: SmokeResult,
    expected_file: Path,
    expected_text: str,
) -> Path:
    if not run_id:
        raise SmokeFailure("No current session was created.")
    run_dir = workspace / ".asteria" / "runs" / run_id
    base_required_files = [
        run_dir / "run.json",
        run_dir / "goal_spec.json",
        run_dir / "task_plan.json",
        run_dir / "events.jsonl",
        run_dir / "tool_calls.jsonl",
        run_dir / "model_calls.jsonl",
        run_dir / "cost_report.json",
        run_dir / "final_report.md",
    ]
    required_files = base_required_files
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise SmokeFailure("Missing expected run artifact(s): " + ", ".join(missing))
    empty = [str(path) for path in required_files if path.stat().st_size == 0]
    if empty:
        raise SmokeFailure("Empty run artifact(s): " + ", ".join(empty))
    if not expected_file.exists():
        raise SmokeFailure(f"Expected output file was not created: {expected_file}")
    content = expected_file.read_text(encoding="utf-8")
    if expected_text not in content:
        raise SmokeFailure(
            f"Expected output file does not contain required text: {expected_text!r}"
        )
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    eval_report_path = run_dir / "eval_report.json"
    eval_report = (
        json.loads(eval_report_path.read_text(encoding="utf-8"))
        if eval_report_path.exists()
        else {}
    )
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    result.diagnostics = build_diagnostics(
        run=run,
        eval_report=eval_report,
        task_plan=task_plan,
        cost_report=cost_report,
    )
    if run.get("status") != "completed":
        if not _accept_budget_paused_success(run_dir, run, eval_report):
            raise SmokeFailure(f"Run status is {run.get('status')!r}, expected 'completed'.")
        result.diagnostics["accepted_budget_pause"] = True
    unfinished = [
        f"{task['task_id']}:{task['status']}"
        for task in task_plan.get("tasks", [])
        if task.get("status") not in {"done", "discarded"}
    ]
    if unfinished:
        raise SmokeFailure("Run has unfinished task(s): " + ", ".join(unfinished))
    model_call_count = count_jsonl(run_dir / "model_calls.jsonl")
    tool_call_count = count_jsonl(run_dir / "tool_calls.jsonl")
    if int(cost_report.get("model_calls", 0)) != model_call_count:
        raise SmokeFailure(
            "cost_report.json model_calls does not match model_calls.jsonl: "
            f"{cost_report.get('model_calls')} != {model_call_count}"
        )
    if int(cost_report.get("tool_calls", 0)) != tool_call_count:
        raise SmokeFailure(
            "cost_report.json tool_calls does not match tool_calls.jsonl: "
            f"{cost_report.get('tool_calls')} != {tool_call_count}"
        )
    if int(cost_report.get("model_calls", 0)) <= 0:
        raise SmokeFailure("cost_report.json did not record model calls.")
    if int(cost_report.get("tool_calls", 0)) <= 0:
        raise SmokeFailure("cost_report.json did not record tool calls.")
    return run_dir / "final_report.md"


def _accept_budget_paused_success(
    run_dir: Path, run: dict[str, Any], eval_report: dict[str, Any]
) -> bool:
    if run.get("status") != "paused":
        return False
    if eval_report.get("overall", {}).get("status") != "pass":
        return False
    pending = pending_decisions(run_dir.parents[2], str(run.get("run_id") or ""))
    return bool(pending) and all(is_budget_guard_decision(decision) for decision in pending)


def build_diagnostics(
    *,
    run: dict[str, Any],
    eval_report: dict[str, Any],
    task_plan: dict[str, Any],
    cost_report: dict[str, Any],
) -> dict[str, Any]:
    task_status_counts: dict[str, int] = {}
    for task in task_plan.get("tasks", []):
        status = str(task.get("status") or "unknown")
        task_status_counts[status] = task_status_counts.get(status, 0) + 1
    return {
        "run_status": run.get("status"),
        "review_status": eval_report.get("overall", {}).get("status"),
        "review_score": eval_report.get("overall", {}).get("score"),
        "task_status_counts": task_status_counts,
        "model_calls": int(cost_report.get("model_calls", 0)),
        "tool_calls": int(cost_report.get("tool_calls", 0)),
        "estimated_input_tokens": int(cost_report.get("estimated_input_tokens", 0)),
        "estimated_output_tokens": int(cost_report.get("estimated_output_tokens", 0)),
        "repair_attempts": int(cost_report.get("repair_attempts", 0)),
        "context_compactions": int(cost_report.get("context_compactions", 0)),
        "cost_status": cost_report.get("status"),
    }


def count_jsonl(path: Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def text_or_empty(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def write_transcript(result: SmokeResult) -> None:
    result.transcript.parent.mkdir(parents=True, exist_ok=True)
    result.transcript.write_text(
        json.dumps(result.summary(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def redact(value: str) -> str:
    redacted = value
    for name in SECRET_ENV_NAMES:
        secret = os.getenv(name)
        if secret:
            redacted = redacted.replace(secret, f"<redacted:{name}>")
    return redacted


def print_success(result: SmokeResult) -> None:
    print("Real model smoke passed")
    print(f"Workspace: {result.workspace}")
    print(f"Session: {result.run_id}")
    print(f"Artifact: {result.expected_file}")
    print(f"Final report: {result.final_report}")
    print(f"Transcript: {result.transcript}")


def print_failure(exc: Exception, result: SmokeResult) -> None:
    print(f"Real model smoke failed: {exc}", file=sys.stderr)
    print(f"Workspace: {result.workspace}", file=sys.stderr)
    print(f"Session: {result.run_id or 'not created'}", file=sys.stderr)
    print(f"Transcript: {result.transcript}", file=sys.stderr)


def print_matrix_summary(summary: dict[str, Any], matrix_summary_path: Path) -> None:
    status = "passed" if summary["ok"] else "failed"
    print(f"Real model smoke matrix {status}")
    print(f"Matrix: {summary['matrix']}")
    print(f"Cases: {summary['passed']}/{summary['case_count']} passed")
    print(f"Summary: {matrix_summary_path}")
    for case in summary["cases"]:
        marker = "PASS" if case["ok"] else "FAIL"
        print(f"- {marker} {case['name']} [{case['route']}]: {case['reason']}")


if __name__ == "__main__":
    main()
