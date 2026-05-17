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
        os.environ.setdefault(
            "AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES",
            str(args.model_max_retries),
        )
        os.environ.setdefault(
            "AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS",
            str(args.command_timeout_seconds),
        )
        workspace, cleanup = prepare_workspace(args.root)
        result = SmokeResult(
            workspace=workspace,
            run_id=None,
            expected_file=workspace / args.expected_file,
            final_report=None,
            transcript=workspace / "real_model_smoke_transcript.json",
        )
        run_smoke(args, result)
        result.ended_at = time.monotonic()
        write_transcript(result)
        if args.summary_json:
            args.summary_json.parent.mkdir(parents=True, exist_ok=True)
            args.summary_json.write_text(
                json.dumps(result.summary(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print_success(result)
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic script boundary
        if result:
            result.ended_at = time.monotonic()
        if result:
            write_transcript(result)
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
        default=5,
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
        help="Optional path for a machine-readable smoke summary.",
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
        raise SmokeFailure("asteria /run failed; see transcript for command output.")

    if (
        not args.no_recovery
        and result.run_id
        and (workspace / ".asteria" / "runs" / result.run_id / "goal_spec.json").exists()
        and not (workspace / ".asteria" / "runs" / result.run_id / "eval_report.json").exists()
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
) -> CommandRecord:
    env = os.environ.copy()
    env.setdefault("AGENT_MODEL_MAX_RETRIES", str(args_model_max_retries()))
    completed = subprocess.run(
        [python, "-m", "asteria_runtime", *args],
        cwd=result.workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=int(os.getenv("AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS", "900")),
    )
    record = CommandRecord(
        name=name,
        command=["python", "-m", "asteria_runtime", *args],
        returncode=completed.returncode,
        stdout=redact(completed.stdout),
        stderr=redact(completed.stderr),
    )
    result.commands.append(record)
    if check and completed.returncode != 0:
        raise SmokeFailure(f"{name} failed with exit code {completed.returncode}.")
    return record


def args_model_max_retries() -> int:
    return int(os.getenv("AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES", "5"))


def merge_pythonpath(src_path: str, current: str | None) -> str:
    if not current:
        return src_path
    paths = current.split(os.pathsep)
    if src_path in paths:
        return current
    return os.pathsep.join([src_path, current])


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
    required_files = [
        run_dir / "run.json",
        run_dir / "goal_spec.json",
        run_dir / "task_plan.json",
        run_dir / "events.jsonl",
        run_dir / "tool_calls.jsonl",
        run_dir / "model_calls.jsonl",
        run_dir / "cost_report.json",
        run_dir / "eval_report.json",
        run_dir / "review_report.md",
        run_dir / "final_report.md",
    ]
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
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
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
    review_status = eval_report.get("overall", {}).get("status")
    if review_status != "pass":
        raise SmokeFailure(f"Review status is {review_status!r}, expected 'pass'.")
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


if __name__ == "__main__":
    main()
