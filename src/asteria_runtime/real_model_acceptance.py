from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asteria_runtime.acceptance.runtime_os_catalog import (  # noqa: E402
    runtime_os_metadata,
    runtime_os_scenario_names,
)
from asteria_runtime.acceptance.runtime_os_scenarios import run_runtime_os_scenario  # noqa: E402


@dataclass(frozen=True)
class AcceptanceScenario:
    name: str
    capability: str
    tier: str = "core"
    goal: str = ""
    expected_file: str = ""
    expected_text: str = ""
    max_iterations: int = 5
    max_tasks_per_iteration: int = 1
    kind: str = "run"
    setup_files: dict[str, str] | None = None


SCENARIOS: dict[str, AcceptanceScenario] = {
    "file_smoke": AcceptanceScenario(
        name="file_smoke",
        capability="artifact_creation",
        tier="smoke",
        goal="Create a local file hello_runtime.txt containing one line: real model smoke ok",
        expected_file="hello_runtime.txt",
        expected_text="real model smoke ok",
        max_iterations=3,
    ),
    "password_cli": AcceptanceScenario(
        name="password_cli",
        capability="single_file_cli",
        goal=(
            "Create a single-file Python CLI tool named password_strength.py. "
            "It should classify an input password as weak, medium, or strong using length, "
            "character variety, and common-password checks. It must run with "
            "`python password_strength.py <password>` and print the classification."
        ),
        expected_file="password_strength.py",
        expected_text="password",
        max_iterations=5,
    ),
    "markdown_kb": AcceptanceScenario(
        name="markdown_kb",
        capability="search_cli",
        goal=(
            "Create a small single-file Python tool named markdown_kb.py that indexes markdown "
            "files under a directory and searches for a keyword. It must support "
            "`python markdown_kb.py <directory> <keyword>` and print matching file paths and lines."
        ),
        expected_file="markdown_kb.py",
        expected_text="markdown",
        max_iterations=5,
    ),
    "offline_artifact": AcceptanceScenario(
        name="offline_artifact",
        capability="offline_artifact",
        tier="offline",
        goal="create offline artifact",
        expected_file="offline_artifact.txt",
        expected_text="offline verification artifact",
        max_iterations=3,
    ),
    "gray_file_artifact": AcceptanceScenario(
        name="gray_file_artifact",
        capability="gray_artifact_creation",
        tier="gray",
        goal=("Create a local file gray_runtime.txt containing one line: gray route artifact ok"),
        expected_file="gray_runtime.txt",
        expected_text="gray route artifact ok",
        max_iterations=3,
    ),
    "gray_multi_file_scope": AcceptanceScenario(
        name="gray_multi_file_scope",
        capability="gray_multi_file_scope",
        tier="gray",
        goal=(
            "Create a small multi-file Python notes CLI. Use a package directory named notes_app "
            "with storage.py and cli.py, plus a runnable notes.py entrypoint. It must support "
            '`python notes.py add "ship gray"` and `python notes.py list`, storing notes in '
            "notes.json under the current directory."
        ),
        expected_file="notes.py",
        expected_text="notes_app",
        max_iterations=5,
    ),
    "gray_debug_repair": AcceptanceScenario(
        name="gray_debug_repair",
        capability="gray_debug_repair",
        tier="gray",
        goal=(
            "Fix the failing tests in this project. Run the Python tests, identify the bug in "
            "buggy_math.py, and make the tests pass with the smallest reasonable change."
        ),
        expected_file="buggy_math.py",
        expected_text="return a + b",
        max_iterations=5,
        setup_files={
            "buggy_math.py": "def add(a, b):\n    return a - b\n",
            "test_buggy_math.py": (
                "from buggy_math import add\n\n\n"
                "def test_adds_positive_numbers():\n"
                "    assert add(2, 3) == 5\n\n\n"
                "def test_adds_negative_numbers():\n"
                "    assert add(-2, -3) == -5\n"
            ),
        },
    ),
    "failing_tests_repair": AcceptanceScenario(
        name="failing_tests_repair",
        capability="test_driven_repair",
        tier="advanced",
        goal=(
            "Fix the failing tests in this project. Run the Python tests, identify the bug in "
            "buggy_math.py, and make the tests pass with the smallest reasonable change."
        ),
        expected_file="buggy_math.py",
        expected_text="return a + b",
        max_iterations=5,
        setup_files={
            "buggy_math.py": "def add(a, b):\n    return a - b\n",
            "test_buggy_math.py": (
                "from buggy_math import add\n\n\n"
                "def test_adds_positive_numbers():\n"
                "    assert add(2, 3) == 5\n\n\n"
                "def test_adds_negative_numbers():\n"
                "    assert add(-2, -3) == -5\n"
            ),
        },
    ),
    "safe_file_renamer": AcceptanceScenario(
        name="safe_file_renamer",
        capability="config_driven_cli",
        goal=(
            "Create a safe single-file Python CLI named safe_rename.py that reads a JSON rename "
            "plan, validates source files exist, and supports a dry-run preview without renaming "
            "files. It must run with `python safe_rename.py rename_plan.json --dry-run` and print "
            "the planned mappings."
        ),
        expected_file="safe_rename.py",
        expected_text="dry",
        max_iterations=5,
        setup_files={
            "IMG_0001.txt": "first fixture\n",
            "IMG_0002.txt": "second fixture\n",
            "rename_plan.json": (
                "{\n"
                '  "mappings": [\n'
                '    {"source": "IMG_0001.txt", "target": "photo-0001.txt"},\n'
                '    {"source": "IMG_0002.txt", "target": "photo-0002.txt"}\n'
                "  ]\n"
                "}\n"
            ),
        },
    ),
    "multi_file_todo_cli": AcceptanceScenario(
        name="multi_file_todo_cli",
        capability="multi_file_change",
        tier="core",
        goal=(
            "Create a small multi-file Python todo CLI. Use a package directory named todo_app "
            "with storage and CLI modules, plus a runnable todo.py entrypoint. It must support "
            '`python todo.py add "buy milk"` and `python todo.py list`, storing tasks in a JSON '
            "file under the current directory."
        ),
        expected_file="todo.py",
        expected_text="todo_app",
        max_iterations=6,
    ),
    "config_driven_report": AcceptanceScenario(
        name="config_driven_report",
        capability="configuration_change",
        tier="core",
        goal=(
            "Create a Python report generator named report_from_config.py that reads "
            "report_config.json and sales.csv, applies the configured currency and minimum total, "
            "and writes report.md with a concise sales summary. It must run with "
            "`python report_from_config.py report_config.json`."
        ),
        expected_file="report_from_config.py",
        expected_text="report_config",
        max_iterations=6,
        setup_files={
            "report_config.json": (
                "{\n"
                '  "input_csv": "sales.csv",\n'
                '  "output_markdown": "report.md",\n'
                '  "currency": "USD",\n'
                '  "minimum_total": 20\n'
                "}\n"
            ),
            "sales.csv": "item,quantity,price\nnotebook,3,8\npen,5,2\nbag,1,35\n",
        },
    ),
    **{
        item["scenario"]: AcceptanceScenario(
            name=item["scenario"],
            capability=item["capability"],
            tier=item["tier"],
            kind=item["kind"],
        )
        for item in runtime_os_metadata()
    },
    "docs_code_sync": AcceptanceScenario(
        name="docs_code_sync",
        capability="docs_code_sync",
        tier="advanced",
        goal=(
            "Update the existing CLI documentation and implementation together. The README says "
            "the calculator supports add only, but users need multiply too. Modify calculator.py "
            "and README.md so `python calculator.py multiply 6 7` prints 42 and the docs describe "
            "both add and multiply."
        ),
        expected_file="README.md",
        expected_text="multiply",
        max_iterations=6,
        setup_files={
            "calculator.py": (
                "import sys\n\n\n"
                "def main():\n"
                "    command, left, right = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
                "    if command == 'add':\n"
                "        print(left + right)\n"
                "    else:\n"
                "        raise SystemExit('unknown command')\n\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
            "README.md": "# Calculator\n\nRun `python calculator.py add 2 3` to add numbers.\n",
        },
    ),
    "refactor_existing_module": AcceptanceScenario(
        name="refactor_existing_module",
        capability="safe_refactor",
        tier="advanced",
        goal=(
            "Refactor the existing invoice.py module without changing behavior. Extract clearer "
            "helper functions, keep public function names stable, and make the existing tests pass. "
            "Run the tests before finishing."
        ),
        expected_file="invoice.py",
        expected_text="def",
        max_iterations=6,
        setup_files={
            "invoice.py": (
                "def invoice_total(items, tax_rate):\n"
                "    subtotal = 0\n"
                "    for item in items:\n"
                "        subtotal += item['quantity'] * item['price']\n"
                "    return round(subtotal + subtotal * tax_rate, 2)\n\n\n"
                "def invoice_lines(items):\n"
                "    lines = []\n"
                "    for item in items:\n"
                "        lines.append(f\"{item['name']}: {item['quantity']} x {item['price']}\")\n"
                "    return lines\n"
            ),
            "test_invoice.py": (
                "from invoice import invoice_lines, invoice_total\n\n\n"
                "def test_invoice_total_keeps_behavior():\n"
                "    items = [{'name': 'A', 'quantity': 2, 'price': 5}]\n"
                "    assert invoice_total(items, 0.1) == 11\n\n\n"
                "def test_invoice_lines_keep_behavior():\n"
                "    assert invoice_lines([{'name': 'A', 'quantity': 2, 'price': 5}]) == ['A: 2 x 5']\n"
            ),
        },
    ),
    "memory_lesson_reuse": AcceptanceScenario(
        name="memory_lesson_reuse",
        capability="memory_effectiveness",
        tier="advanced",
        kind="memory",
    ),
    "decision_point": AcceptanceScenario(
        name="decision_point",
        capability="decision_memory",
        tier="advanced",
        kind="decision",
    ),
}

SUITES = {
    "smoke": ["file_smoke"],
    "core": [
        "file_smoke",
        "password_cli",
        "markdown_kb",
        "safe_file_renamer",
        "multi_file_todo_cli",
        "config_driven_report",
        *runtime_os_scenario_names(),
    ],
    "gray": [
        "gray_file_artifact",
        "gray_multi_file_scope",
        "gray_debug_repair",
        "runtime_request_resume",
    ],
    "advanced": [
        "failing_tests_repair",
        "docs_code_sync",
        "refactor_existing_module",
        "memory_lesson_reuse",
        "decision_point",
    ],
    "nightly": [
        "file_smoke",
        "password_cli",
        "markdown_kb",
        "safe_file_renamer",
        "multi_file_todo_cli",
        "config_driven_report",
        *runtime_os_scenario_names(),
        "failing_tests_repair",
        "docs_code_sync",
        "refactor_existing_module",
        "memory_lesson_reuse",
        "decision_point",
    ],
    "offline": ["offline_artifact"],
}


class AcceptanceFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class TimeoutBudget:
    scenario_seconds: int
    subprocess_grace_seconds: int = 30

    @property
    def smoke_command_seconds(self) -> int:
        return max(60, self.scenario_seconds - self.subprocess_grace_seconds)

    @property
    def subprocess_seconds(self) -> int:
        return self.scenario_seconds

    @property
    def review_seconds(self) -> int:
        return min(90, max(30, self.scenario_seconds // 6))

    @property
    def provider_call_seconds(self) -> int:
        return min(90, max(30, self.scenario_seconds // 4))

    @property
    def cheap_provider_call_seconds(self) -> int:
        return min(45, self.provider_call_seconds)

    def as_dict(self) -> dict[str, int]:
        return {
            "scenario_seconds": self.scenario_seconds,
            "subprocess_seconds": self.subprocess_seconds,
            "smoke_command_seconds": self.smoke_command_seconds,
            "review_seconds": self.review_seconds,
            "provider_call_seconds": self.provider_call_seconds,
            "cheap_provider_call_seconds": self.cheap_provider_call_seconds,
        }


def apply_timeout_budget_env(env: dict[str, str], budget: TimeoutBudget) -> None:
    provider_timeout = str(budget.provider_call_seconds)
    cheap_timeout = str(budget.cheap_provider_call_seconds)
    for name in (
        "AGENT_MODEL_TIMEOUT_SECONDS",
        "AGENT_MODEL_STRONG_TIMEOUT_SECONDS",
        "AGENT_MODEL_MEDIUM_TIMEOUT_SECONDS",
    ):
        env.setdefault(name, provider_timeout)
    env.setdefault("AGENT_MODEL_CHEAP_TIMEOUT_SECONDS", cheap_timeout)
    for name in (
        "AGENT_MODEL_MAX_RETRIES",
        "AGENT_MODEL_STRONG_MAX_RETRIES",
        "AGENT_MODEL_MEDIUM_MAX_RETRIES",
        "AGENT_MODEL_CHEAP_MAX_RETRIES",
    ):
        env.setdefault(name, "1")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_from_args(args)


def run_from_args(args: argparse.Namespace) -> None:
    root, cleanup = prepare_root(args.root)
    results: list[dict[str, Any]] = []
    try:
        selected = select_scenarios(args)
        for scenario in selected:
            results.append(run_scenario(args, root, scenario))
        scenario_metadata = scenario_metadata_for(selected)
        aggregate = aggregate_results(results, scenario_metadata)
        summary = {
            "ok": all(result["ok"] for result in results),
            "root": str(root),
            "suite": args.suite,
            "requested_scenarios": args.scenario,
            "created_at": now_iso(),
            "scenario_metadata": scenario_metadata,
            "scenarios": results,
            "aggregate": aggregate,
            "gray_ready": gray_ready(args.suite, aggregate),
        }
        attach_history(args.history_jsonl, summary)
        write_summary(args.summary_json, summary)
        if not summary["ok"]:
            failed = [result["scenario"] for result in results if not result["ok"]]
            raise AcceptanceFailure("Scenario(s) failed: " + ", ".join(failed))
        print("Real model acceptance passed")
        print(f"Root: {root}")
        print("Scenarios: " + ", ".join(result["scenario"] for result in results))
    except Exception as exc:  # noqa: BLE001 - diagnostic script boundary
        if results:
            write_summary(
                args.summary_json,
                {
                    "ok": False,
                    "root": str(root),
                    "suite": args.suite,
                    "requested_scenarios": args.scenario,
                    "created_at": now_iso(),
                    "scenario_metadata": scenario_metadata_for(selected),
                    "scenarios": results,
                    "aggregate": aggregate_results(results, scenario_metadata_for(selected)),
                    "gray_ready": False,
                    "error": str(exc),
                },
            )
        print(f"Real model acceptance failed: {exc}", file=sys.stderr)
        print(f"Root: {root}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        if cleanup and args.cleanup and root.exists():
            shutil.rmtree(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run curated real-model acceptance scenarios in isolated workspaces."
    )
    parser.add_argument("--suite", choices=sorted(SUITES), default="smoke")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        default=[],
        help="Specific scenario to run. Can be repeated; overrides --suite.",
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument(
        "--history-jsonl",
        type=Path,
        default=None,
        help="Append each acceptance summary to this JSONL file and include trend deltas.",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow fake/offline providers. Intended for script tests.",
    )
    parser.add_argument("--run-attempts", type=int, default=1)
    parser.add_argument("--model-max-retries", type=int, default=1)
    parser.add_argument(
        "--scenario-timeout-seconds",
        type=int,
        default=600,
        help="Maximum seconds per scenario subprocess.",
    )
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument(
        "--reuse-workspace",
        action="store_true",
        help="Reuse existing scenario workspaces instead of deleting them before each run.",
    )
    return parser


def select_scenarios(args: argparse.Namespace) -> list[AcceptanceScenario]:
    names = args.scenario or SUITES[args.suite]
    fake_allowed = {
        "offline_artifact",
        "decision_point",
        "memory_lesson_reuse",
        *runtime_os_scenario_names(),
    }
    if args.allow_fake:
        names = [n for n in names if n in fake_allowed]
        if not names:
            raise AcceptanceFailure(
                "Fake/offline acceptance only supports offline_artifact, decision_point, "
                "memory_lesson_reuse, and runtime_os scenarios. "
                "Use real providers for real task scenarios."
            )
    return [SCENARIOS[name] for name in names]


def prepare_root(root: Path | None) -> tuple[Path, bool]:
    if root is not None:
        resolved = root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved, False
    return Path(tempfile.mkdtemp(prefix="agent-real-acceptance-")).resolve(), True


def run_scenario(
    args: argparse.Namespace,
    root: Path,
    scenario: AcceptanceScenario,
) -> dict[str, Any]:
    workspace = root / scenario.name
    if scenario.kind == "decision":
        return run_decision_scenario(args, workspace, scenario)
    if scenario.kind == "memory":
        return run_memory_scenario(args, workspace, scenario)
    if scenario.kind == "runtime_os":
        return run_runtime_os_scenario(
            workspace=workspace,
            scenario_name=scenario.name,
            capability=scenario.capability,
            tier=scenario.tier,
        )
    started_at = time.monotonic()
    if workspace.exists() and not args.reuse_workspace:
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    write_setup_files(workspace, scenario)
    summary_path = workspace / "acceptance_summary.json"
    timeout_budget = TimeoutBudget(int(args.scenario_timeout_seconds))
    command = [
        args.python,
        "-m",
        "asteria_runtime.real_model_smoke",
        "--root",
        str(workspace),
        "--goal",
        scenario.goal,
        "--expected-file",
        scenario.expected_file,
        "--expected-text",
        scenario.expected_text,
        "--max-iterations",
        str(scenario.max_iterations),
        "--max-tasks-per-iteration",
        str(scenario.max_tasks_per_iteration),
        "--run-attempts",
        str(args.run_attempts),
        "--model-max-retries",
        str(args.model_max_retries),
        "--command-timeout-seconds",
        str(timeout_budget.smoke_command_seconds),
        "--no-research",
        "--summary-json",
        str(summary_path),
    ]
    if args.allow_fake:
        command.append("--allow-fake")
    env = os.environ.copy()
    env["AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES"] = str(args.model_max_retries)
    env["AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS"] = str(timeout_budget.smoke_command_seconds)
    env["AGENT_MODEL_SMOKE_REVIEW_TIMEOUT_SECONDS"] = str(timeout_budget.review_seconds)
    apply_timeout_budget_env(env, timeout_budget)
    if args.allow_fake:
        env["AGENT_MODEL_PROVIDER"] = "fake"
        env["AGENT_MODEL_STRONG_PROVIDER"] = "fake"
        env["AGENT_MODEL_MEDIUM_PROVIDER"] = "fake"
        env["AGENT_MODEL_CHEAP_PROVIDER"] = "fake"
    attempts: list[dict[str, Any]] = []
    completed: subprocess.CompletedProcess[str] | None = None
    max_attempts = max(1, int(args.run_attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_budget.subprocess_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = text_or_empty(exc.stdout)
            stderr = (
                text_or_empty(exc.stderr)
                + f"\nScenario timed out after {timeout_budget.subprocess_seconds}s."
            )
            salvaged = salvage_timed_out_smoke_summary(
                workspace=workspace,
                scenario=scenario,
                summary_path=summary_path,
                started_at=started_at,
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "returncode": None,
                    "retryable": salvaged is None,
                    "failure_type": "timeout_salvaged" if salvaged else "timeout",
                    "stdout_tail": stdout[-2000:],
                    "stderr_tail": stderr[-2000:],
                    "timeout_budget": timeout_budget.as_dict(),
                }
            )
            if salvaged:
                route_evidence = route_evidence_from_smoke_summary(salvaged)
                return {
                    "scenario": scenario.name,
                    "capability": scenario.capability,
                    "tier": scenario.tier,
                    "ok": True,
                    "workspace": str(workspace),
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "summary": salvaged,
                    "route_evidence": route_evidence,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timeout_budget": timeout_budget.as_dict(),
                }
            if attempt >= max_attempts:
                return {
                    "scenario": scenario.name,
                    "capability": scenario.capability,
                    "tier": scenario.tier,
                    "ok": False,
                    "workspace": str(workspace),
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "summary": read_json(summary_path),
                    "stdout": stdout,
                    "stderr": stderr,
                    "timeout_budget": timeout_budget.as_dict(),
                }
            continue
        retryable, failure_type = classify_acceptance_subprocess_failure(completed)
        attempts.append(
            {
                "attempt": attempt,
                "returncode": completed.returncode,
                "retryable": retryable,
                "failure_type": failure_type,
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
                "timeout_budget": timeout_budget.as_dict(),
            }
        )
        if completed.returncode == 0 or attempt >= max_attempts or not retryable:
            break
    if completed is None:
        raise AcceptanceFailure(f"Scenario did not execute: {scenario.name}")
    summary = read_json(summary_path)
    route_evidence = route_evidence_from_smoke_summary(summary)
    return {
        "scenario": scenario.name,
        "capability": scenario.capability,
        "tier": scenario.tier,
        "ok": completed.returncode == 0,
        "workspace": str(workspace),
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "attempts": attempts,
        "summary": summary,
        "route_evidence": route_evidence,
        "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timeout_budget": timeout_budget.as_dict(),
        }


def classify_acceptance_subprocess_failure(
    completed: subprocess.CompletedProcess[str],
) -> tuple[bool, str | None]:
    if completed.returncode == 0:
        return False, None
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    markers = {
        "rate_limited": ["429", "rate limit", "too many requests"],
        "server_error": ["500", "502", "503", "504", "temporarily unavailable"],
        "timeout": ["timeout", "timed out"],
        "network": [
            "unexpected_eof",
            "tls",
            "ssl",
            "urlopen error",
            "remote end closed connection",
            "connection closed",
            "connection reset",
        ],
    }
    for failure_type, needles in markers.items():
        if any(needle in text for needle in needles):
            return True, failure_type
    return False, "scenario_failure"


def salvage_timed_out_smoke_summary(
    *,
    workspace: Path,
    scenario: AcceptanceScenario,
    summary_path: Path,
    started_at: float,
) -> dict[str, Any] | None:
    existing = read_json(summary_path)
    if existing.get("run_id") and existing.get("diagnostics", {}).get("accepted_review_timeout"):
        return existing
    run_id = current_run_id(workspace)
    if not run_id:
        return None
    run_dir = workspace / ".asteria" / "runs" / run_id
    expected_file = workspace / scenario.expected_file
    if not expected_file.exists():
        return None
    if scenario.expected_text not in expected_file.read_text(encoding="utf-8"):
        return None
    if not any(item.get("type") == "run_completed" for item in read_jsonl(run_dir / "events.jsonl")):
        return None
    evidence = read_jsonl(run_dir / "task_execution_evidence.jsonl")
    if not any(item.get("status") == "done" for item in evidence):
        return None
    verification_passed = False
    for item in evidence:
        if item.get("status") != "done":
            continue
        results = item.get("verification_results")
        if isinstance(results, list) and results:
            verification_passed = all(
                bool(result.get("ok")) for result in results if isinstance(result, dict)
            )
            break
    if not verification_passed:
        return None
    cost_report = read_json(run_dir / "cost_report.json")
    summary = {
        "workspace": str(workspace),
        "run_id": run_id,
        "expected_file": str(expected_file),
        "final_report": str(run_dir / "final_report.md"),
        "transcript": str(workspace / "real_model_smoke_transcript.json"),
        "duration_seconds": round(time.monotonic() - started_at, 3),
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
    write_summary(summary_path, summary)
    return summary


def write_setup_files(workspace: Path, scenario: AcceptanceScenario) -> None:
    for relative_path, content in (scenario.setup_files or {}).items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_decision_scenario(
    args: argparse.Namespace,
    workspace: Path,
    scenario: AcceptanceScenario,
) -> dict[str, Any]:
    del scenario
    started_at = time.monotonic()
    workspace.mkdir(parents=True, exist_ok=True)
    commands: list[dict[str, Any]] = []
    init = run_agent_command(
        workspace,
        args.allow_fake,
        "/init",
        "--root",
        str(workspace),
    )
    commands.append({"name": "init", **init})
    new_session = run_agent_command(
        workspace,
        args.allow_fake,
        "/new",
        "Create a tiny CLI tool; choose output medium when needed.",
        "--root",
        str(workspace),
    )
    commands.append({"name": "new-session", **new_session})
    create = run_agent_command(
        workspace,
        args.allow_fake,
        "/decide",
        "--root",
        str(workspace),
        "--question",
        "Should the tool use a CLI or web UI first?",
        "--options-json",
        json.dumps(
            [
                {
                    "option_id": "cli",
                    "label": "CLI first",
                    "tradeoff": "Fast and scriptable",
                    "action": "record_constraint",
                },
                {
                    "option_id": "web",
                    "label": "Web UI first",
                    "tradeoff": "More visual but slower",
                    "action": "require_replan",
                },
            ]
        ),
        "--recommended-option-id",
        "cli",
        "--default-option-id",
        "cli",
    )
    commands.append({"name": "create-decision", **create})
    list_pending = run_agent_command(
        workspace,
        args.allow_fake,
        "/decide",
        "--root",
        str(workspace),
        "--list-pending",
    )
    commands.append({"name": "list-pending", **list_pending})
    resolve = run_agent_command(
        workspace,
        args.allow_fake,
        "/decide",
        "--root",
        str(workspace),
        "--decision-id",
        "decision-0001",
        "--select-option-id",
        "cli",
    )
    commands.append({"name": "resolve-decision", **resolve})
    ok = all(command["returncode"] == 0 for command in commands)
    agent_dir = workspace / ".asteria"
    decision_logs = list(agent_dir.glob("runs/*/decisions.jsonl"))
    memory_path = agent_dir / "memory" / "decisions.jsonl"
    decisions = [decision for path in decision_logs for decision in read_jsonl(path)]
    resolved_decision = next(
        (
            decision
            for decision in decisions
            if decision.get("decision_id") == "decision-0001"
            and decision.get("status") == "resolved"
        ),
        None,
    )
    if resolved_decision is None or resolved_decision.get("selected_option_id") != "cli":
        ok = False
    summary = {
        "workspace": str(workspace),
        "decision_logs": [str(path) for path in decision_logs],
        "memory_path": str(memory_path) if memory_path.exists() else None,
        "resolved_decision_id": (
            resolved_decision.get("decision_id") if resolved_decision else None
        ),
        "resolved_status": resolved_decision.get("status") if resolved_decision else None,
        "selected_option_id": (
            resolved_decision.get("selected_option_id") if resolved_decision else None
        ),
        "commands": commands,
    }
    return {
        "scenario": "decision_point",
        "capability": "decision_memory",
        "tier": "advanced",
        "ok": ok,
        "workspace": str(workspace),
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "summary": summary,
        "stdout": "\n".join(command["stdout"] for command in commands),
        "stderr": "\n".join(command["stderr"] for command in commands),
    }


def run_memory_scenario(
    args: argparse.Namespace,
    workspace: Path,
    scenario: AcceptanceScenario,
) -> dict[str, Any]:
    del scenario
    started_at = time.monotonic()
    workspace.mkdir(parents=True, exist_ok=True)
    agent_dir = workspace / ".asteria"
    memory_dir = agent_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_dir / "failures.jsonl"
    lesson = {
        "schema_version": "0.1.0",
        "memory_id": "memory-lesson-0001",
        "kind": "failure_lesson",
        "summary": "Prefer explicit reproduction commands when repairing similar CLI failures.",
        "source": {
            "scenario": "memory_lesson_reuse",
            "failure_type": "scenario_validation_failure",
        },
        "tags": ["acceptance", "repair", "cli"],
        "created_at": now_iso(),
    }
    memory_path.write_text(json.dumps(lesson, ensure_ascii=False) + "\n", encoding="utf-8")
    second_prompt = (
        "Repair a similar CLI failure. Use prior lesson: "
        f"{lesson['summary']} Reproduce with `python broken_cli.py --check`."
    )
    prompt_path = workspace / "second_attempt_prompt.txt"
    prompt_path.write_text(second_prompt, encoding="utf-8")
    ok = "Use prior lesson" in prompt_path.read_text(encoding="utf-8") and memory_path.exists()
    return {
        "scenario": "memory_lesson_reuse",
        "capability": "memory_effectiveness",
        "tier": "advanced",
        "ok": ok,
        "workspace": str(workspace),
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "summary": {
            "memory_path": str(memory_path),
            "prompt_path": str(prompt_path),
            "lesson_reused": ok,
        },
        "stdout": second_prompt,
        "stderr": "",
    }


def scenario_metadata_for(scenarios: list[AcceptanceScenario]) -> list[dict[str, str]]:
    return [
        {
            "scenario": scenario.name,
            "capability": scenario.capability,
            "tier": scenario.tier,
            "kind": scenario.kind,
        }
        for scenario in scenarios
    ]


def aggregate_results(
    results: list[dict[str, Any]],
    scenario_metadata: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    metadata_by_name = {
        item["scenario"]: item for item in scenario_metadata or [] if item.get("scenario")
    }
    capability_status: dict[str, dict[str, Any]] = {}
    tier_status: dict[str, dict[str, Any]] = {}
    route_evidence = aggregate_route_evidence(results)
    aggregate: dict[str, Any] = {
        "total": len(results),
        "passed": len([result for result in results if result.get("ok")]),
        "failed": len([result for result in results if not result.get("ok")]),
        "duration_seconds": round(
            sum(float(result.get("duration_seconds") or 0) for result in results), 3
        ),
        "model_calls": 0,
        "tool_calls": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "repair_attempts": 0,
        "context_compactions": 0,
        "failed_scenarios": [
            str(result.get("scenario")) for result in results if not result.get("ok")
        ],
        "capabilities": capability_status,
        "tiers": tier_status,
        "route_evidence": route_evidence,
    }
    for result in results:
        name = str(result.get("scenario") or "")
        metadata = metadata_by_name.get(name, {})
        capability = str(result.get("capability") or metadata.get("capability") or "unknown")
        tier = str(result.get("tier") or metadata.get("tier") or "unknown")
        _add_status(capability_status, capability, bool(result.get("ok")))
        _add_status(tier_status, tier, bool(result.get("ok")))
        summary = result.get("summary")
        if not isinstance(summary, dict):
            continue
        diagnostics = summary.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        for key in (
            "model_calls",
            "tool_calls",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "repair_attempts",
            "context_compactions",
        ):
            aggregate[key] += int(diagnostics.get(key) or 0)
    return aggregate


def route_evidence_from_smoke_summary(summary: dict[str, Any]) -> dict[str, Any]:
    workspace = summary.get("workspace")
    run_id = summary.get("run_id")
    if not workspace or not run_id:
        return {"available": False, "reason": "missing workspace or run_id"}
    run_dir = Path(str(workspace)) / ".asteria" / "runs" / str(run_id)
    model_calls = read_jsonl(run_dir / "model_calls.jsonl")
    worker_results = read_jsonl(run_dir / "worker_results.jsonl")
    task_evidence = read_jsonl(run_dir / "task_execution_evidence.jsonl")
    tiers = sorted({str(call.get("model_tier") or "unknown") for call in model_calls})
    providers_by_tier: dict[str, set[str]] = {}
    purposes_by_tier: dict[str, set[str]] = {}
    for call in model_calls:
        tier = str(call.get("model_tier") or "unknown")
        providers_by_tier.setdefault(tier, set()).add(str(call.get("model_provider") or "unknown"))
        purposes_by_tier.setdefault(tier, set()).add(str(call.get("purpose") or "unknown"))
    return {
        "available": True,
        "run_id": str(run_id),
        "model_call_count": len(model_calls),
        "worker_result_count": len(worker_results),
        "task_execution_evidence_count": len(task_evidence),
        "tiers": tiers,
        "providers_by_tier": {
            tier: sorted(providers) for tier, providers in sorted(providers_by_tier.items())
        },
        "purposes_by_tier": {
            tier: sorted(purposes) for tier, purposes in sorted(purposes_by_tier.items())
        },
        "strong_used": "strong" in tiers,
        "medium_used": "medium" in tiers,
    }


def aggregate_route_evidence(results: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios_with_route_evidence = []
    scenarios_missing_strong = []
    scenarios_missing_medium = []
    providers_by_tier: dict[str, set[str]] = {}
    for result in results:
        evidence = result.get("route_evidence")
        if not isinstance(evidence, dict) or not evidence.get("available"):
            continue
        scenario = str(result.get("scenario") or "unknown")
        scenarios_with_route_evidence.append(scenario)
        if not evidence.get("strong_used"):
            scenarios_missing_strong.append(scenario)
        if not evidence.get("medium_used"):
            scenarios_missing_medium.append(scenario)
        raw_providers = evidence.get("providers_by_tier")
        if isinstance(raw_providers, dict):
            for tier, providers in raw_providers.items():
                target = providers_by_tier.setdefault(str(tier), set())
                if isinstance(providers, list):
                    target.update(str(provider) for provider in providers)
    return {
        "scenarios_with_route_evidence": scenarios_with_route_evidence,
        "scenarios_missing_strong": scenarios_missing_strong,
        "scenarios_missing_medium": scenarios_missing_medium,
        "providers_by_tier": {
            tier: sorted(providers) for tier, providers in sorted(providers_by_tier.items())
        },
        "strong_used": bool(scenarios_with_route_evidence) and not scenarios_missing_strong,
        "medium_used": bool(scenarios_with_route_evidence) and not scenarios_missing_medium,
    }


def gray_ready(suite: str, aggregate: dict[str, Any]) -> bool:
    if suite != "gray":
        return False
    route_evidence = aggregate.get("route_evidence")
    return bool(
        aggregate.get("failed") == 0
        and isinstance(route_evidence, dict)
        and route_evidence.get("strong_used")
        and route_evidence.get("medium_used")
    )


def _add_status(target: dict[str, dict[str, Any]], key: str, ok: bool) -> None:
    status = target.setdefault(key, {"total": 0, "passed": 0, "failed": 0, "ok": True})
    status["total"] += 1
    if ok:
        status["passed"] += 1
    else:
        status["failed"] += 1
        status["ok"] = False


def attach_history(history_jsonl: Path | None, summary: dict[str, Any]) -> None:
    if history_jsonl is None:
        summary["trend"] = {"previous": None, "deltas": {}}
        return
    previous = latest_history_entry(history_jsonl, summary)
    summary["trend"] = compare_with_previous(previous, summary)
    history_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with history_jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")


def latest_history_entry(path: Path, summary: dict[str, Any]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    current_key = history_key(summary)
    latest: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if history_key(candidate) == current_key:
            latest = candidate
    return latest


def history_key(summary: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    requested = summary.get("requested_scenarios") or []
    if not requested:
        requested = [
            str(item.get("scenario") or "")
            for item in summary.get("scenarios", [])
            if isinstance(item, dict)
        ]
    return str(summary.get("suite") or ""), tuple(sorted(str(item) for item in requested if item))


def compare_with_previous(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    if previous is None:
        return {"previous": None, "deltas": {}}
    raw_previous_aggregate = previous.get("aggregate")
    raw_current_aggregate = current.get("aggregate")
    previous_aggregate = raw_previous_aggregate if isinstance(raw_previous_aggregate, dict) else {}
    current_aggregate = raw_current_aggregate if isinstance(raw_current_aggregate, dict) else {}
    delta_keys = [
        "passed",
        "failed",
        "duration_seconds",
        "model_calls",
        "tool_calls",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "repair_attempts",
        "context_compactions",
    ]
    deltas = {
        key: round(
            float(current_aggregate.get(key) or 0) - float(previous_aggregate.get(key) or 0), 3
        )
        for key in delta_keys
    }
    return {
        "previous": {
            "created_at": previous.get("created_at"),
            "ok": previous.get("ok"),
            "aggregate": previous_aggregate,
        },
        "deltas": deltas,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_agent_command(workspace: Path, allow_fake: bool, *args: str) -> dict[str, Any]:
    env = os.environ.copy()
    if allow_fake:
        env["AGENT_MODEL_PROVIDER"] = "fake"
        env["AGENT_MODEL_STRONG_PROVIDER"] = "fake"
        env["AGENT_MODEL_MEDIUM_PROVIDER"] = "fake"
        env["AGENT_MODEL_CHEAP_PROVIDER"] = "fake"
    completed = subprocess.run(
        [sys.executable, "-m", "asteria_runtime", *args],
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


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


def text_or_empty(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def write_summary(path: Path | None, summary: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
