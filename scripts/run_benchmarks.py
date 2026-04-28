from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.run_command import RunCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.models.fake import FakeModelClient


@dataclass
class BenchmarkResult:
    benchmark_id: str
    ok: bool
    workspace: Path
    run_id: str | None = None
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "ok": self.ok,
            "workspace": str(self.workspace),
            "run_id": self.run_id,
            "checks": self.checks,
            "failures": self.failures,
        }


class FailingProjectPlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": "fix failing tests",
            "normalized_goal": "Fix the failing buggy_math test project",
            "goal_type": "codebase_improvement",
            "assumptions": ["pytest is the verification command"],
            "constraints": ["local_first", "no_network"],
            "non_goals": ["large refactor"],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": "Repair buggy_math.add so the local pytest suite passes",
                    "source": "user",
                    "acceptance": ["python -m pytest tests passes"],
                }
            ],
            "target_outputs": ["python_module", "tests"],
            "definition_of_done": ["pytest passes", "final report lists the repair"],
            "verification_strategy": ["python -m pytest tests"],
            "budget": {"max_iterations": 8, "max_model_calls": 60},
        }
        return _response(request, payload)


class FailingProjectExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task = json.loads(request.messages[-1].content)["task"]
        payload = {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Run the current failing test suite to capture baseline failure.",
            "tool_calls": [],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {"command": "python -m pytest tests"},
                    "reason": "capture failing verification before repair",
                }
            ],
            "completion_notes": "baseline verification should fail before repair",
        }
        return _response(request, payload)


class FailingProjectRepairClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task = json.loads(request.messages[-1].content)["task"]
        payload = {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Repair buggy_math.add to add numbers.",
            "tool_calls": [
                {
                    "tool_name": "apply_patch",
                    "args": {
                        "patch": (
                            "--- a/buggy_math.py\n"
                            "+++ b/buggy_math.py\n"
                            "@@\n"
                            " def add(a: int, b: int) -> int:\n"
                            "-    return a - b\n"
                            "+    return a + b\n"
                        )
                    },
                    "reason": "replace subtraction with addition",
                }
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {"command": "python -m pytest tests"},
                    "reason": "verify repaired test suite",
                }
            ],
            "completion_notes": "buggy_math.add now adds numbers and pytest passes",
        }
        return _response(request, payload)


def run_benchmarks(
    benchmark_ids: list[str] | None = None,
    work_dir: Path | None = None,
    keep_workspaces: bool = False,
) -> list[BenchmarkResult]:
    ids = benchmark_ids or ["password_tool", "failing_tests_project"]
    results: list[BenchmarkResult] = []
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=True)
        for benchmark_id in ids:
            workspace = work_dir / benchmark_id
            if workspace.exists():
                shutil.rmtree(workspace)
            workspace.mkdir(parents=True)
            results.append(_run_one(benchmark_id, workspace))
        return results

    with tempfile.TemporaryDirectory(prefix="agent-benchmarks-") as tmp:
        root = Path(tmp)
        for benchmark_id in ids:
            workspace = root / benchmark_id
            workspace.mkdir(parents=True)
            results.append(_run_one(benchmark_id, workspace))
        if keep_workspaces:
            kept = REPO_ROOT / ".agent" / "benchmark-workspaces"
            kept.mkdir(parents=True, exist_ok=True)
            for result in results:
                target = kept / result.benchmark_id
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(result.workspace, target)
                result.workspace = target
        return results


def _run_one(benchmark_id: str, workspace: Path) -> BenchmarkResult:
    if benchmark_id == "password_tool":
        return _run_password_tool(workspace)
    if benchmark_id == "failing_tests_project":
        return _run_failing_tests_project(workspace)
    raise ValueError(f"Unknown benchmark: {benchmark_id}")


def _run_password_tool(workspace: Path) -> BenchmarkResult:
    result = BenchmarkResult("password_tool", ok=False, workspace=workspace)
    manifest = _manifest("password_tool")
    try:
        run = RunCommand(
            workspace,
            goal=manifest["goal"],
            model_client=FakeModelClient(),
            enable_research=False,
        ).run()
        result.run_id = run.run_id
        run_dir = workspace / ".agent" / "runs" / run.run_id
        _check_expected_files(result, run_dir, manifest["expected_artifacts"])
        goal_spec = _read_json(run_dir / "goal_spec.json")
        constraints = set(goal_spec.get("constraints", []))
        _check(result, bool({"local_first", "privacy_safe", "no_network"} & constraints), "goal has local/privacy constraint")
        _check(result, (workspace / "offline_artifact.txt").exists(), "offline artifact exists")
        _check_report_mentions(result, run_dir / "final_report.md", ["Artifacts", "Model calls", "Tool calls"])
    except Exception as exc:  # noqa: BLE001 - benchmark runner reports failures instead of crashing
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def _run_failing_tests_project(workspace: Path) -> BenchmarkResult:
    result = BenchmarkResult("failing_tests_project", ok=False, workspace=workspace)
    manifest = _manifest("failing_tests_project")
    try:
        _copy_fixtures("failing_tests_project", workspace)
        tests_dir = workspace / "tests"
        tests_dir.mkdir(exist_ok=True)
        shutil.move(str(workspace / "test_buggy_math.py"), tests_dir / "test_buggy_math.py")

        InitCommand(workspace).run()
        plan = PlanCommand(workspace, manifest["goal"], model_client=FailingProjectPlanClient()).run()
        execute = ExecuteCommand(
            workspace,
            run_id=plan.run_id,
            model_client=FailingProjectExecuteClient(),
        ).run()
        _check(result, execute.blocked == 1, "baseline execution blocks on failing tests")
        debug = DebugCommand(
            workspace,
            run_id=plan.run_id,
            model_client=FailingProjectRepairClient(),
        ).run()
        _check(result, debug.repaired == 1, "debug repairs the failing task")
        final = RunCommand(
            workspace,
            run_id=plan.run_id,
            model_client=FakeModelClient(),
            enable_research=False,
        ).run()
        result.run_id = final.run_id

        run_dir = workspace / ".agent" / "runs" / plan.run_id
        _check_expected_files(result, run_dir, manifest["expected_artifacts"])
        experiments = _read_jsonl(run_dir / "experiments.jsonl")
        _check(
            result,
            any(
                item["decision"] == "discard"
                and item["metrics_after"]["verification_pass_rate"] == 0.0
                for item in experiments
            ),
            "failed candidate is discarded",
        )
        _check(result, (workspace / "buggy_math.py").read_text(encoding="utf-8").strip().endswith("a + b"), "source repaired")
        _check(result, bool(list((workspace / ".agent" / "backups").glob("*/*/manifest.json"))), "backup manifest exists")
        _check_report_mentions(result, run_dir / "final_report.md", ["Artifacts", "buggy_math.py"])
    except Exception as exc:  # noqa: BLE001
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def _manifest(benchmark_id: str) -> dict:
    return _read_json(REPO_ROOT / "benchmarks" / benchmark_id / "benchmark.json")


def _copy_fixtures(benchmark_id: str, workspace: Path) -> None:
    manifest = _manifest(benchmark_id)
    for fixture in manifest.get("fixtures", []):
        source = REPO_ROOT / "benchmarks" / benchmark_id / fixture
        shutil.copy2(source, workspace / source.name)


def _check_expected_files(result: BenchmarkResult, run_dir: Path, names: list[str]) -> None:
    for name in names:
        _check(result, (run_dir / name).exists(), f"{name} exists")


def _check_report_mentions(result: BenchmarkResult, path: Path, terms: list[str]) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    for term in terms:
        _check(result, term in content, f"{path.name} mentions {term}")


def _check(result: BenchmarkResult, condition: bool, label: str) -> None:
    if condition:
        result.checks.append(label)
    else:
        result.failures.append(label)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _response(request: ChatRequest, payload: dict) -> ChatResponse:
    content = json.dumps(payload, ensure_ascii=False)
    return ChatResponse(
        content=content,
        finish_reason="stop",
        usage=TokenUsage(
            input_tokens=max(1, sum(len(message.content) for message in request.messages) // 4),
            output_tokens=max(1, len(content) // 4),
            total_tokens=None,
            usage_estimated=True,
        ),
        model_provider="benchmark",
        model_name="deterministic-benchmark",
        raw_response={"purpose": request.purpose},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic agent runtime benchmarks.")
    parser.add_argument(
        "benchmarks",
        nargs="*",
        help="Benchmark ids to run; defaults to all MVP benchmarks.",
    )
    parser.add_argument("--work-dir", type=Path, default=None, help="Directory for benchmark workspaces")
    parser.add_argument("--keep-workspaces", action="store_true", help="Copy temp workspaces under .agent")
    args = parser.parse_args()

    results = run_benchmarks(
        benchmark_ids=args.benchmarks or None,
        work_dir=args.work_dir,
        keep_workspaces=args.keep_workspaces,
    )
    print(json.dumps([result.to_dict() for result in results], indent=2, ensure_ascii=False))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
