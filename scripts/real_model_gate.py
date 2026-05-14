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
    returncode: int
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
    routes: dict[str, dict[str, str | None]] = field(default_factory=dict)
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


def main() -> None:
    args = build_parser().parse_args()
    workspace, cleanup = prepare_workspace(args.root)
    result = GateResult(workspace=workspace)
    try:
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
        if cleanup and args.cleanup and workspace.exists():
            shutil.rmtree(workspace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the controlled real-model gate before gray release validation."
    )
    parser.add_argument("--root", type=Path, default=None, help="Gate workspace root.")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Machine-readable gate report. Defaults to <root>/.agent/model/real_model_gate_report.json.",
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
        default=2,
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
        raise GateFailure("AGENT_MODEL_STRONG_PROVIDER is required for gray gate.")
    if not medium:
        raise GateFailure("AGENT_MODEL_MEDIUM_PROVIDER is required for gray gate.")
    if not allow_fake and (strong in OFFLINE_PROVIDERS or medium in OFFLINE_PROVIDERS):
        raise GateFailure("fake/offline routes require --allow-fake and are not gray-release evidence.")
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
    result.checks["strong_model_check"] = run_command(
        result,
        args.python,
        "-m",
        "agent_runtime",
        "/model-check",
        "--root",
        str(result.workspace),
        "--tier",
        "strong",
        name="model-check-strong",
    ).returncode == 0
    result.checks["medium_model_check"] = run_command(
        result,
        args.python,
        "-m",
        "agent_runtime",
        "/model-check",
        "--root",
        str(result.workspace),
        "--tier",
        "medium",
        name="model-check-medium",
    ).returncode == 0
    smoke_summary = result.workspace / ".agent" / "model" / "real_model_smoke_summary.json"
    smoke_args = [
        "scripts/real_model_smoke.py",
        "--root",
        str(result.workspace),
        "--summary-json",
        str(smoke_summary),
        "--run-attempts",
        str(args.smoke_run_attempts),
        "--no-research",
    ]
    if route_provider("strong") in OFFLINE_PROVIDERS or route_provider("medium") in OFFLINE_PROVIDERS:
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
    result.checks["smoke"] = run_command(
        result,
        args.python,
        *smoke_args,
        name="real-model-smoke",
    ).returncode == 0
    result.smoke_summary = read_json(smoke_summary)
    inspect_smoke_evidence(result)


def inspect_smoke_evidence(result: GateResult) -> None:
    run_id = result.smoke_summary.get("run_id")
    if not run_id:
        result.failures.append("smoke summary did not include a run_id")
        return
    run_dir = result.workspace / ".agent" / "runs" / str(run_id)
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
    result.checks["cost_report_consistent"] = int(cost_report.get("model_calls", -1)) == len(model_calls)
    for check, ok in result.checks.items():
        if not ok:
            result.failures.append(f"check failed: {check}")


def run_command(
    result: GateResult,
    python: str,
    *args: str,
    name: str,
) -> GateCommand:
    env = os.environ.copy()
    env["PYTHONPATH"] = merge_pythonpath(str((repo_root() / "src").resolve()), env.get("PYTHONPATH"))
    completed = subprocess.run(
        [python, *args],
        cwd=repo_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=int(os.getenv("AGENT_MODEL_GATE_COMMAND_TIMEOUT_SECONDS", "900")),
    )
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


def route_summary() -> dict[str, dict[str, str | None]]:
    return {
        tier: {
            "provider": route_provider(tier),
            "model": route_env(tier, "NAME"),
            "base_url": route_env(tier, "BASE_URL"),
        }
        for tier in ("strong", "medium", "cheap")
    }


def route_provider(tier: str) -> str:
    return route_env(tier, "PROVIDER").lower()


def route_env(tier: str, key: str) -> str:
    value = os.getenv(f"AGENT_MODEL_{tier.upper()}_{key}")
    if value is not None:
        return value
    return os.getenv(f"AGENT_MODEL_{key}", "")


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
    raise GateFailure(f"AGENT_MODEL_{tier.upper()}_API_KEY is required for {provider}.")


def write_report(args: argparse.Namespace, result: GateResult) -> None:
    path = report_path(args, result.workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report_path(args: argparse.Namespace, workspace: Path) -> Path:
    if args.summary_json:
        return args.summary_json.resolve()
    return workspace / ".agent" / "model" / "real_model_gate_report.json"


def recommended_actions(failures: list[str]) -> list[str]:
    if not failures:
        return [
            "Run `python scripts/real_model_acceptance.py --suite gray` before core acceptance."
        ]
    actions = ["Fix failed route checks before gray release validation."]
    if any("strong" in failure for failure in failures):
        actions.append("Check GLM/coordinator provider key, endpoint, JSON response, and tier routing.")
    if any("medium" in failure for failure in failures):
        actions.append("Check MiniMax/worker provider key, endpoint, JSON response, and tier routing.")
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def merge_pythonpath(src_path: str, current: str | None) -> str:
    if not current:
        return src_path
    paths = current.split(os.pathsep)
    if src_path in paths:
        return current
    return os.pathsep.join([src_path, current])


def redact(value: str) -> str:
    redacted = value
    for name in SECRET_ENV_NAMES:
        secret = os.getenv(name)
        if secret:
            redacted = redacted.replace(secret, f"<redacted:{name}>")
    return redacted


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
