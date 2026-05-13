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
            "`python todo.py add \"buy milk\"` and `python todo.py list`, storing tasks in a JSON "
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


def main() -> None:
    args = build_parser().parse_args()
    root, cleanup = prepare_root(args.root)
    results: list[dict[str, Any]] = []
    try:
        selected = select_scenarios(args)
        for scenario in selected:
            results.append(run_scenario(args, root, scenario))
        scenario_metadata = scenario_metadata_for(selected)
        summary = {
            "ok": all(result["ok"] for result in results),
            "root": str(root),
            "suite": args.suite,
            "requested_scenarios": args.scenario,
            "created_at": now_iso(),
            "scenario_metadata": scenario_metadata,
            "scenarios": results,
            "aggregate": aggregate_results(results, scenario_metadata),
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
    parser.add_argument("--run-attempts", type=int, default=2)
    parser.add_argument("--model-max-retries", type=int, default=5)
    parser.add_argument(
        "--scenario-timeout-seconds",
        type=int,
        default=1200,
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
    fake_allowed = {"offline_artifact", "decision_point", "memory_lesson_reuse"}
    if args.allow_fake and any(name not in fake_allowed for name in names):
        raise AcceptanceFailure(
            "Fake/offline acceptance only supports offline_artifact and decision_point. "
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
    started_at = time.monotonic()
    if workspace.exists() and not args.reuse_workspace:
        shutil.rmtree(workspace)
    write_setup_files(workspace, scenario)
    summary_path = workspace / "acceptance_summary.json"
    command = [
        args.python,
        "scripts/real_model_smoke.py",
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
        str(args.scenario_timeout_seconds),
        "--no-research",
        "--summary-json",
        str(summary_path),
    ]
    if args.allow_fake:
        command.append("--allow-fake")
    env = os.environ.copy()
    env["AGENT_MODEL_SMOKE_MODEL_MAX_RETRIES"] = str(args.model_max_retries)
    env["AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS"] = str(args.scenario_timeout_seconds)
    if args.allow_fake:
        env["AGENT_MODEL_PROVIDER"] = "fake"
    attempts: list[dict[str, Any]] = []
    completed: subprocess.CompletedProcess[str] | None = None
    max_attempts = max(1, int(args.run_attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            completed = subprocess.run(
                command,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=args.scenario_timeout_seconds + 30,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = text_or_empty(exc.stdout)
            stderr = (
                text_or_empty(exc.stderr)
                + f"\nScenario timed out after {args.scenario_timeout_seconds + 30}s."
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "returncode": None,
                    "retryable": True,
                    "failure_type": "timeout",
                    "stdout_tail": stdout[-2000:],
                    "stderr_tail": stderr[-2000:],
                }
            )
            if attempt >= max_attempts:
                return {
                    "scenario": scenario.name,
                    "ok": False,
                    "workspace": str(workspace),
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "summary": read_json(summary_path),
                    "stdout": stdout,
                    "stderr": stderr,
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
            }
        )
        if completed.returncode == 0 or attempt >= max_attempts or not retryable:
            break
    if completed is None:
        raise AcceptanceFailure(f"Scenario did not execute: {scenario.name}")
    return {
        "scenario": scenario.name,
        "capability": scenario.capability,
        "tier": scenario.tier,
        "ok": completed.returncode == 0,
        "workspace": str(workspace),
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "attempts": attempts,
        "summary": read_json(summary_path),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
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
        "network": ["unexpected_eof", "tls", "ssl", "urlopen error"],
    }
    for failure_type, needles in markers.items():
        if any(needle in text for needle in needles):
            return True, failure_type
    return False, "scenario_failure"


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
    agent_dir = workspace / ".agent"
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
    agent_dir = workspace / ".agent"
    memory_dir = agent_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_dir / "failures.jsonl"
    lesson = {
        "schema_version": "0.1.0",
        "memory_id": "memory-lesson-0001",
        "kind": "failure_lesson",
        "summary": "Prefer explicit reproduction commands when repairing similar CLI failures.",
        "source": {"scenario": "memory_lesson_reuse", "failure_type": "scenario_validation_failure"},
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
    previous_aggregate = (
        previous.get("aggregate") if isinstance(previous.get("aggregate"), dict) else {}
    )
    current_aggregate = (
        current.get("aggregate") if isinstance(current.get("aggregate"), dict) else {}
    )
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
    src_path = str((Path(__file__).resolve().parents[1] / "src").resolve())
    env["PYTHONPATH"] = (
        src_path if not env.get("PYTHONPATH") else os.pathsep.join([src_path, env["PYTHONPATH"]])
    )
    completed = subprocess.run(
        [sys.executable, "-m", "agent_runtime", *args],
        cwd=Path(__file__).resolve().parents[1],
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


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


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
