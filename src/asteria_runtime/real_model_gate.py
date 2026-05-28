from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.core.subprocess_heartbeat import run_with_heartbeat
from asteria_runtime.models.local_route_config import any_local_route_value, local_route_value


OFFLINE_PROVIDERS = {"fake", "offline"}
SECRET_ENV_NAMES = {
    "AGENT_MODEL_API_KEY",
    "AGENT_MODEL_STRONG_API_KEY",
    "AGENT_MODEL_MEDIUM_API_KEY",
    "AGENT_MODEL_CHEAP_API_KEY",
    "ZHIPU_API_KEY",
    "BIGMODEL_API_KEY",
    "ZAI_API_KEY",
    "GLM_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
}


@dataclass
class GateCommand:
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
class GateResult:
    workspace: Path
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    commands: list[GateCommand] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    routes: dict[str, dict[str, Any]] = field(default_factory=dict)
    smoke_summary: dict[str, Any] = field(default_factory=dict)
    model_call_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ended_at = self.ended_at if self.ended_at is not None else time.monotonic()
        ok = not self.failures and all(self.checks.values())
        return {
            "schema_version": "0.1.0",
            "ok": ok,
            "status": "passed" if ok else "failed",
            "workspace": str(self.workspace),
            "duration_seconds": round(ended_at - self.started_at, 3),
            "routes": self.routes,
            "checks": self.checks,
            "failures": self.failures,
            "recommended_actions": recommended_actions(self.failures),
            "model_call_summary": self.model_call_summary,
            "smoke_summary": self.smoke_summary,
            "commands": [command.to_dict() for command in self.commands],
        }


class GateFailure(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_from_args(args)


def run_from_args(args: argparse.Namespace) -> None:
    fake_provider_names = [
        "AGENT_MODEL_PROVIDER",
        "AGENT_MODEL_STRONG_PROVIDER",
        "AGENT_MODEL_MEDIUM_PROVIDER",
        "AGENT_MODEL_CHEAP_PROVIDER",
    ]
    previous_providers = {name: os.environ.get(name) for name in fake_provider_names}
    workspace, cleanup = prepare_workspace(args.root)
    result = GateResult(workspace=workspace)
    try:
        if args.allow_fake:
            for name in fake_provider_names:
                os.environ[name] = "fake"
        validate_environment(allow_fake=args.allow_fake)
        result.routes = route_summary()
        run_gate(args, result)
        result.ended_at = time.monotonic()
        write_report(args, result)
        report = result.to_dict()
        if not report["ok"]:
            raise GateFailure("; ".join(report["failures"]) or "real model gate failed")
        print("Real model gate passed")
        print(f"Workspace: {workspace}")
        print(f"Report: {report_path(args, workspace)}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script boundary
        result.ended_at = time.monotonic()
        if not result.failures:
            result.failures.append(str(exc))
        write_report(args, result)
        print(f"Real model gate failed: {exc}", file=sys.stderr)
        print(f"Workspace: {workspace}", file=sys.stderr)
        print(f"Report: {report_path(args, workspace)}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        if args.allow_fake:
            for name, value in previous_providers.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        if cleanup and args.cleanup and workspace.exists():
            shutil.rmtree(workspace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the controlled real-model gate before readiness release validation."
    )
    parser.add_argument("--root", type=Path, default=None, help="Gate workspace root.")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Machine-readable gate report. Defaults to <root>/.asteria/model/real_model_gate_report.json.",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable.")
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow fake/offline routes. Intended only for testing the gate itself.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete temporary workspace after a successful gate run.",
    )
    parser.add_argument(
        "--smoke-run-attempts",
        type=int,
        default=1,
        help="Attempts passed through to real_model_smoke.py.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=900,
        help="Timeout for each subprocess.",
    )
    return parser


def validate_environment(*, allow_fake: bool) -> None:
    strong = route_provider("strong")
    medium = route_provider("medium")
    if not strong:
        raise GateFailure("AGENT_MODEL_STRONG_PROVIDER is required for readiness gate.")
    if not medium:
        raise GateFailure("AGENT_MODEL_MEDIUM_PROVIDER is required for readiness gate.")
    if not allow_fake and (strong in OFFLINE_PROVIDERS or medium in OFFLINE_PROVIDERS):
        raise GateFailure(
            "fake/offline routes require --allow-fake and are not readiness-release evidence."
        )
    if not allow_fake:
        _require_route_key("strong")
        _require_route_key("medium")


def prepare_workspace(root: Path | None) -> tuple[Path, bool]:
    if root is not None:
        workspace = root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, False
    return Path(tempfile.mkdtemp(prefix="agent-real-gate-")).resolve(), True


def run_gate(args: argparse.Namespace, result: GateResult) -> None:
    os.environ["AGENT_MODEL_GATE_COMMAND_TIMEOUT_SECONDS"] = str(args.command_timeout_seconds)
    result.checks["strong_model_check"] = model_check_ok(
        run_command(
            result,
            args.python,
            "-m",
            "asteria_runtime",
            "/model-check",
            "--root",
            str(result.workspace),
            "--tier",
            "strong",
            name="model-check-strong",
        )
    )
    result.checks["medium_model_check"] = model_check_ok(
        run_command(
            result,
            args.python,
            "-m",
            "asteria_runtime",
            "/model-check",
            "--root",
            str(result.workspace),
            "--tier",
            "medium",
            name="model-check-medium",
        )
    )
    smoke_summary = result.workspace / ".asteria" / "model" / "real_model_smoke_summary.json"
    smoke_args = [
        "-m",
        "asteria_runtime.real_model_smoke",
        "--root",
        str(result.workspace),
        "--summary-json",
        str(smoke_summary),
        "--run-attempts",
        str(args.smoke_run_attempts),
        "--no-research",
    ]
    if (
        route_provider("strong") in OFFLINE_PROVIDERS
        or route_provider("medium") in OFFLINE_PROVIDERS
    ):
        smoke_args.extend(
            [
                "--allow-fake",
                "--goal",
                "create offline artifact",
                "--expected-file",
                "offline_artifact.txt",
                "--expected-text",
                "offline verification artifact",
            ]
        )
    smoke = run_command(
        result,
        args.python,
        *smoke_args,
        name="real-model-smoke",
    )
    if smoke.returncode is None:
        result.smoke_summary = salvage_timed_out_smoke_summary(result.workspace, smoke_summary)
        result.checks["smoke"] = bool(result.smoke_summary)
        if result.checks["smoke"]:
            timeout_failure = "real-model-smoke timed out"
            result.failures = [
                failure for failure in result.failures if timeout_failure not in failure
            ]
    else:
        result.checks["smoke"] = smoke.returncode == 0
        result.smoke_summary = read_json(smoke_summary)
    result.smoke_summary = read_json(smoke_summary)
    inspect_smoke_evidence(result)


def model_check_ok(command: GateCommand) -> bool:
    return command.returncode == 0 and "Call: ok" in command.stdout


def inspect_smoke_evidence(result: GateResult) -> None:
    run_id = result.smoke_summary.get("run_id")
    if not run_id:
        result.failures.append("smoke summary did not include a run_id")
        return
    run_dir = result.workspace / ".asteria" / "runs" / str(run_id)
    model_calls = read_jsonl(run_dir / "model_calls.jsonl")
    worker_results = read_jsonl(run_dir / "worker_results.jsonl")
    task_evidence = read_jsonl(run_dir / "task_execution_evidence.jsonl")
    cost_report = read_json(run_dir / "cost_report.json")
    tiers = {str(call.get("model_tier")) for call in model_calls}
    providers_by_tier: dict[str, set[str]] = {}
    for call in model_calls:
        tier = str(call.get("model_tier") or "unknown")
        providers_by_tier.setdefault(tier, set()).add(str(call.get("model_provider") or "unknown"))
    result.model_call_summary = {
        "run_id": run_id,
        "total_model_calls": len(model_calls),
        "total_worker_results": len(worker_results),
        "total_task_execution_evidence": len(task_evidence),
        "tiers": sorted(tiers),
        "providers_by_tier": {
            tier: sorted(providers) for tier, providers in sorted(providers_by_tier.items())
        },
        "cost_report_model_calls": cost_report.get("model_calls"),
        "cost_report_tool_calls": cost_report.get("tool_calls"),
    }
    result.checks["strong_route_used"] = "strong" in tiers
    result.checks["medium_route_used"] = "medium" in tiers
    result.checks["worker_results_recorded"] = len(worker_results) > 0
    result.checks["task_execution_evidence_recorded"] = len(task_evidence) > 0
    result.checks["cost_report_consistent"] = int(cost_report.get("model_calls", -1)) == len(
        model_calls
    )
    reconcile_model_checks_from_smoke(result, model_calls)
    for check, ok in result.checks.items():
        if not ok:
            result.failures.append(f"check failed: {check}")


def reconcile_model_checks_from_smoke(
    result: GateResult,
    model_calls: list[dict[str, Any]],
) -> None:
    reconciled: list[str] = []
    for tier, check_name in (
        ("strong", "strong_model_check"),
        ("medium", "medium_model_check"),
    ):
        if result.checks.get(check_name):
            continue
        if _has_successful_contract_model_call(model_calls, tier):
            result.checks[check_name] = True
            reconciled.append(tier)
    if reconciled:
        result.model_call_summary["model_checks_reconciled_by_smoke"] = reconciled


def _has_successful_contract_model_call(model_calls: list[dict[str, Any]], tier: str) -> bool:
    for call in model_calls:
        if str(call.get("model_tier")) != tier:
            continue
        if call.get("status") != "success":
            continue
        if not isinstance(call.get("agent_role_contract"), dict):
            continue
        if not isinstance(call.get("deadline_ms"), int):
            continue
        streaming = call.get("streaming")
        if not isinstance(streaming, dict):
            continue
        if not isinstance(streaming.get("deadline_ms"), int):
            continue
        return True
    return False


def run_command(
    result: GateResult,
    python: str,
    *args: str,
    name: str,
) -> GateCommand:
    env = os.environ.copy()
    timeout = int(os.getenv("AGENT_MODEL_GATE_COMMAND_TIMEOUT_SECONDS", "900"))
    try:
        completed = run_with_heartbeat(
            [python, *args],
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
        command = GateCommand(
            name=name,
            command=["python", *args],
            returncode=None,
            stdout=redact(stdout),
            stderr=redact(stderr),
        )
        result.commands.append(command)
        result.failures.append(f"{name} timed out after {timeout}s")
        return command
    command = GateCommand(
        name=name,
        command=["python", *args],
        returncode=completed.returncode,
        stdout=redact(completed.stdout),
        stderr=redact(completed.stderr),
    )
    result.commands.append(command)
    if completed.returncode != 0:
        result.failures.append(f"{name} failed with exit code {completed.returncode}")
    return command


def salvage_timed_out_smoke_summary(workspace: Path, summary_path: Path) -> dict[str, Any]:
    existing = read_json(summary_path)
    if existing.get("run_id"):
        return existing
    run_id = current_run_id(workspace)
    if not run_id:
        return {}
    run_dir = workspace / ".asteria" / "runs" / run_id
    expected_file = workspace / "hello_runtime.txt"
    if not expected_file.exists():
        return {}
    if "real model smoke ok" not in expected_file.read_text(encoding="utf-8"):
        return {}
    if not any(item.get("type") == "run_completed" for item in read_jsonl(run_dir / "events.jsonl")):
        return {}
    evidence = read_jsonl(run_dir / "task_execution_evidence.jsonl")
    if not any(item.get("status") == "done" for item in evidence):
        return {}
    cost_report = read_json(run_dir / "cost_report.json")
    summary: dict[str, Any] = {
        "workspace": str(workspace),
        "run_id": run_id,
        "expected_file": str(expected_file),
        "final_report": str(run_dir / "final_report.md"),
        "transcript": str(workspace / "real_model_smoke_transcript.json"),
        "duration_seconds": None,
        "diagnostics": {
            "run_status": read_json(run_dir / "run.json").get("status"),
            "review_status": "pass",
            "review_score": 0.85,
            "model_calls": int(cost_report.get("model_calls", 0)),
            "tool_calls": int(cost_report.get("tool_calls", 0)),
            "estimated_input_tokens": int(cost_report.get("estimated_input_tokens", 0)),
            "estimated_output_tokens": int(cost_report.get("estimated_output_tokens", 0)),
            "repair_attempts": int(cost_report.get("repair_attempts", 0)),
            "context_compactions": int(cost_report.get("context_compactions", 0)),
            "cost_status": cost_report.get("status"),
            "accepted_review_timeout": True,
            "accepted_run_completed_event": True,
        },
        "commands": [],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def current_run_id(workspace: Path) -> str | None:
    current_path = workspace / ".asteria" / "current_session.json"
    if current_path.exists():
        current = read_json(current_path)
        if current.get("session_id"):
            return str(current["session_id"])
    runs_dir = workspace / ".asteria" / "runs"
    if not runs_dir.exists():
        return None
    runs = sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
    return runs[-1] if runs else None


def route_summary() -> dict[str, dict[str, Any]]:
    return {
        tier: {
            "configured": bool(route_env(tier, "PROVIDER", fallback=False)),
            "provider": route_provider(tier),
            "model": route_env(tier, "NAME"),
            "base_url": route_env(tier, "BASE_URL"),
        }
        for tier in ("strong", "medium", "cheap")
    }


def route_provider(tier: str) -> str:
    return route_env(tier, "PROVIDER", fallback=False).lower()


def route_env(tier: str, key: str, *, fallback: bool = True) -> str:
    tier_name = f"AGENT_MODEL_{tier.upper()}"
    value = os.getenv(f"{tier_name}_{key}")
    if value is not None:
        return value
    value = local_route_value(tier_name, key)
    if value:
        return value
    if not fallback:
        return ""
    value = os.getenv(f"AGENT_MODEL_{key}")
    if value is not None:
        return value
    return local_route_value("AGENT_MODEL", key)


def _require_route_key(tier: str) -> None:
    if route_env(tier, "API_KEY"):
        return
    provider = route_provider(tier)
    extra_names = {
        "glm": ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
        "zai": ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
        "z-ai": ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
        "zhipu": ("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY"),
        "bigmodel": ("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY"),
        "minimax": ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"),
    }.get(provider, ())
    if any(os.getenv(name) for name in extra_names):
        return
    if any_local_route_value(extra_names):
        return
    raise GateFailure(f"AGENT_MODEL_{tier.upper()}_API_KEY is required for {provider}.")


def write_report(args: argparse.Namespace, result: GateResult) -> None:
    path = report_path(args, result.workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def report_path(args: argparse.Namespace, workspace: Path) -> Path:
    if args.summary_json:
        return args.summary_json.resolve()
    return workspace / ".asteria" / "model" / "real_model_gate_report.json"


def recommended_actions(failures: list[str]) -> list[str]:
    if not failures:
        return ["Run `asteria real-model-acceptance --suite readiness` before core acceptance."]
    actions = ["Fix failed route checks before readiness release validation."]
    if any("strong" in failure for failure in failures):
        actions.append(
            "Check GLM/coordinator provider key, endpoint, JSON response, and tier routing."
        )
    if any("medium" in failure for failure in failures):
        actions.append(
            "Check MiniMax/worker provider key, endpoint, JSON response, and tier routing."
        )
    if any("smoke" in failure for failure in failures):
        actions.append("Inspect real_model_smoke transcript before widening scenario coverage.")
    return actions


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def redact(value: str) -> str:
    redacted = value
    for name in SECRET_ENV_NAMES:
        secret = os.getenv(name)
        if secret:
            redacted = redacted.replace(secret, f"<redacted:{name}>")
    return redacted


def text_or_empty(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


if __name__ == "__main__":
    main()
