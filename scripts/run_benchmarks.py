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
from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.handoff_command import HandoffCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.run_command import RunCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.sessions_command import SessionsCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator
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


class FileRenamerClient:
    def __init__(self) -> None:
        self.review_client = FakeModelClient()

    def chat(self, request: ChatRequest) -> ChatResponse:
        if request.purpose == "goal_spec":
            return _response(request, self._goal_spec(request))
        if request.purpose == "task_execution":
            return _response(request, self._execution_action(request))
        return self.review_client.chat(request)

    def _goal_spec(self, request: ChatRequest) -> dict:
        goal = _extract_goal(request.messages[-1].content)
        return {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": "Build a safe batch file renamer with dry-run preview",
            "goal_type": "software_tool",
            "assumptions": ["Preview-only execution is the safest MVP slice"],
            "constraints": ["local_first", "no_network", "dry_run_before_apply"],
            "non_goals": ["Apply destructive renames automatically"],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": (
                        "Create a dry-run rename plan and validator without changing source files"
                    ),
                    "source": "user",
                    "acceptance": [
                        "rename_plan.json marks dry_run true",
                        "rename_preview.py validates that source files exist",
                        "original files remain unchanged after verification",
                    ],
                }
            ],
            "target_outputs": ["rename_plan.json", "rename_preview.py", "README_rename_preview.md"],
            "definition_of_done": [
                "Preview plan exists",
                "Preview validator passes",
                "No fixture file is renamed during preview",
            ],
            "verification_strategy": ["python rename_preview.py"],
            "budget": {"max_iterations": 8, "max_model_calls": 60},
        }

    def _execution_action(self, request: ChatRequest) -> dict:
        task = json.loads(request.messages[-1].content)["task"]
        plan = {
            "schema_version": "0.1.0",
            "dry_run": True,
            "mappings": [
                {"source": "IMG_0001.txt", "target": "photo-0001.txt"},
                {"source": "IMG_0002.txt", "target": "photo-0002.txt"},
            ],
        }
        preview_script = """from __future__ import annotations

import json
from pathlib import Path


plan = json.loads(Path("rename_plan.json").read_text(encoding="utf-8"))
assert plan["dry_run"] is True
for mapping in plan["mappings"]:
    source = Path(mapping["source"])
    target = Path(mapping["target"])
    assert source.exists(), f"missing source: {source}"
    assert not target.exists(), f"preview must not create target: {target}"
print(f"preview ok: {len(plan['mappings'])} rename(s)")
"""
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Create a dry-run rename plan and preview validator.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "rename_plan.json",
                        "content": json.dumps(plan, indent=2) + "\n",
                        "overwrite": True,
                    },
                    "reason": "record proposed renames without applying them",
                },
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "rename_preview.py",
                        "content": preview_script,
                        "overwrite": True,
                    },
                    "reason": "validate the preview remains non-destructive",
                },
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "README_rename_preview.md",
                        "content": (
                            "# Rename Preview\n\n"
                            "This MVP only produces a dry-run plan. Review `rename_plan.json` "
                            "and run `python rename_preview.py` before any future apply step.\n"
                        ),
                        "overwrite": True,
                    },
                    "reason": "document the safe preview workflow",
                },
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {"command": "python rename_preview.py"},
                    "reason": "verify preview plan without renaming files",
                }
            ],
            "completion_notes": "Preview artifacts exist and source files remain unchanged.",
        }


class MarkdownKbClient:
    def __init__(self) -> None:
        self.review_client = FakeModelClient()

    def chat(self, request: ChatRequest) -> ChatResponse:
        if request.purpose == "goal_spec":
            return _response(request, self._goal_spec(request))
        if request.purpose == "task_execution":
            return _response(request, self._execution_action(request))
        return self.review_client.chat(request)

    def _goal_spec(self, request: ChatRequest) -> dict:
        goal = _extract_goal(request.messages[-1].content)
        return {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": "Build a local markdown knowledge base search tool",
            "goal_type": "software_tool",
            "assumptions": ["Markdown files are local and UTF-8 encoded"],
            "constraints": ["local_first", "no_network", "filesystem_json_index"],
            "non_goals": ["Vector embeddings", "remote document crawling"],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": "Index local markdown files and search by keyword",
                    "source": "user",
                    "acceptance": [
                        "markdown_kb.py accepts a directory and keyword",
                        "kb_index.json includes fixture markdown files",
                        "searching for runtime returns agent_runtime.md",
                    ],
                }
            ],
            "target_outputs": ["markdown_kb.py", "kb_index.json", "README_markdown_kb.md"],
            "definition_of_done": [
                "Index is generated from local markdown files",
                "Keyword search returns matching file paths and lines",
                "No network access is required",
            ],
            "verification_strategy": ["python markdown_kb.py notes runtime"],
            "budget": {"max_iterations": 8, "max_model_calls": 60},
        }

    def _execution_action(self, request: ChatRequest) -> dict:
        task = json.loads(request.messages[-1].content)["task"]
        script = """from __future__ import annotations

import json
import sys
from pathlib import Path


def build_index(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        rows.append(
            {
                "path": path.as_posix(),
                "title": next((line[2:].strip() for line in lines if line.startswith("# ")), ""),
                "line_count": len(lines),
                "lines": lines,
            }
        )
    return rows


def search(index: list[dict[str, object]], keyword: str) -> list[str]:
    needle = keyword.lower()
    matches: list[str] = []
    for item in index:
        for line_number, line in enumerate(item["lines"], start=1):
            text = str(line)
            if needle in text.lower():
                matches.append(f"{item['path']}:{line_number}: {text}")
    return matches


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python markdown_kb.py <directory> <keyword>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    keyword = argv[2]
    index = build_index(root)
    Path("kb_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    matches = search(index, keyword)
    for match in matches:
        print(match)
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
"""
        seed_index = [
            {
                "path": "notes/agent_runtime.md",
                "title": "Agent Runtime",
                "line_count": 3,
                "lines": [
                    "# Agent Runtime",
                    "",
                    (
                        "The local runtime turns goals into verified artifacts through planning, "
                        "execution, review, and handoff."
                    ),
                ],
            },
            {
                "path": "notes/security.md",
                "title": "Security Notes",
                "line_count": 3,
                "lines": [
                    "# Security Notes",
                    "",
                    (
                        "The runtime keeps protected paths private and prefers local-first workflows "
                        "before network access."
                    ),
                ],
            },
        ]
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Create a local markdown indexer and keyword search CLI.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "markdown_kb.py",
                        "content": script,
                        "overwrite": True,
                    },
                    "reason": "implement local markdown indexing and keyword search",
                },
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "README_markdown_kb.md",
                        "content": (
                            "# Markdown KB\n\n"
                            "Run `python markdown_kb.py notes runtime` to build `kb_index.json` "
                            "and print matching markdown lines. The tool only reads local files.\n"
                        ),
                        "overwrite": True,
                    },
                    "reason": "document local usage and safety boundary",
                },
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "kb_index.json",
                        "content": json.dumps(seed_index, indent=2) + "\n",
                        "overwrite": True,
                    },
                    "reason": "create an initial durable index artifact for review",
                },
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {"command": "python markdown_kb.py notes runtime"},
                    "reason": "verify keyword search against local fixture notes",
                }
            ],
            "completion_notes": "Markdown search CLI and local JSON index are verified.",
        }


def run_benchmarks(
    benchmark_ids: list[str] | None = None,
    work_dir: Path | None = None,
    keep_workspaces: bool = False,
) -> list[BenchmarkResult]:
    ids = benchmark_ids or available_benchmark_ids()
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
    if benchmark_id == "compact_handoff":
        return _run_compact_handoff(workspace)
    if benchmark_id == "file_renamer":
        return _run_file_renamer(workspace)
    if benchmark_id == "markdown_kb":
        return _run_markdown_kb(workspace)
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
        _check(
            result,
            bool({"local_first", "privacy_safe", "no_network"} & constraints),
            "goal has local/privacy constraint",
        )
        _check(result, (workspace / "offline_artifact.txt").exists(), "offline artifact exists")
        _check_report_mentions(
            result, run_dir / "final_report.md", ["Artifacts", "Model calls", "Tool calls"]
        )
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
        plan = PlanCommand(
            workspace, manifest["goal"], model_client=FailingProjectPlanClient()
        ).run()
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
        _check(
            result,
            (workspace / "buggy_math.py").read_text(encoding="utf-8").strip().endswith("a + b"),
            "source repaired",
        )
        _check(
            result,
            bool(list((workspace / ".agent" / "backups").glob("*/*/manifest.json"))),
            "backup manifest exists",
        )
        _check_report_mentions(result, run_dir / "final_report.md", ["Artifacts", "buggy_math.py"])
    except Exception as exc:  # noqa: BLE001
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def _run_compact_handoff(workspace: Path) -> BenchmarkResult:
    result = BenchmarkResult("compact_handoff", ok=False, workspace=workspace)
    manifest = _manifest("compact_handoff")
    try:
        run = RunCommand(
            workspace,
            goal=manifest["goal"],
            model_client=FakeModelClient(),
            enable_research=False,
        ).run()
        result.run_id = run.run_id
        _write_benchmark_verification_summary(workspace)
        compact = CompactCommand(workspace, run_id=run.run_id, focus="benchmark recovery").run()
        handoff = HandoffCommand(workspace, run_id=run.run_id, to_role="FutureRun").run()
        sessions = SessionsCommand(workspace, session_id=run.run_id, include_context=True).run()
        sessions_text = sessions.to_text()
        run_dir = workspace / ".agent" / "runs" / run.run_id
        _check_expected_files(result, run_dir, manifest["expected_artifacts"])
        snapshot = _read_json(compact.snapshot_path)
        package = _read_json(handoff.handoff_path)
        _check(
            result,
            snapshot["verification_summary"]["status"] == "passed",
            "snapshot includes verification summary",
        )
        _check(
            result,
            package["verification_summary"]["status"] == "passed",
            "handoff includes verification summary",
        )
        _check(
            result,
            package["recommended_next_command"] == "review",
            "handoff recommends review after completed run",
        )
        _check(result, "snapshot:" in sessions_text, "sessions context mentions snapshot")
        _check(result, "handoff:" in sessions_text, "sessions context mentions handoff")
        _check(
            result,
            "verification: passed" in sessions_text,
            "sessions context mentions verification",
        )
        _check(result, compact.snapshot_path.exists(), "context snapshot exists")
        _check(result, handoff.handoff_path.exists(), "handoff package exists")
    except Exception as exc:  # noqa: BLE001
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def _run_file_renamer(workspace: Path) -> BenchmarkResult:
    result = BenchmarkResult("file_renamer", ok=False, workspace=workspace)
    manifest = _manifest("file_renamer")
    try:
        _copy_fixtures("file_renamer", workspace)
        run = RunCommand(
            workspace,
            goal=manifest["goal"],
            model_client=FileRenamerClient(),
            enable_research=False,
        ).run()
        result.run_id = run.run_id
        run_dir = workspace / ".agent" / "runs" / run.run_id
        _check_expected_files(result, run_dir, manifest["expected_artifacts"])

        plan = _read_json(workspace / "rename_plan.json")
        _check(result, plan["dry_run"] is True, "rename plan is dry-run")
        _check(result, len(plan["mappings"]) == 2, "rename plan contains fixture mappings")
        _check(result, (workspace / "rename_preview.py").exists(), "preview validator exists")
        _check(result, (workspace / "IMG_0001.txt").exists(), "first source remains")
        _check(result, (workspace / "IMG_0002.txt").exists(), "second source remains")
        _check(result, not (workspace / "photo-0001.txt").exists(), "first target not created")
        _check(result, not (workspace / "photo-0002.txt").exists(), "second target not created")
        _check_report_mentions(
            result,
            run_dir / "final_report.md",
            ["rename_plan.json", "rename_preview.py", "Model calls", "Tool calls"],
        )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def _run_markdown_kb(workspace: Path) -> BenchmarkResult:
    result = BenchmarkResult("markdown_kb", ok=False, workspace=workspace)
    manifest = _manifest("markdown_kb")
    try:
        _copy_fixtures("markdown_kb", workspace)
        run = RunCommand(
            workspace,
            goal=manifest["goal"],
            model_client=MarkdownKbClient(),
            enable_research=False,
        ).run()
        result.run_id = run.run_id
        run_dir = workspace / ".agent" / "runs" / run.run_id
        _check_expected_files(result, run_dir, manifest["expected_artifacts"])

        index = _read_json(workspace / "kb_index.json")
        items = index.get("items", []) if isinstance(index, dict) else index
        paths = {item["path"] for item in items}
        _check(result, (workspace / "markdown_kb.py").exists(), "markdown search CLI exists")
        _check(result, "notes/agent_runtime.md" in paths, "index includes runtime note")
        _check(result, "notes/security.md" in paths, "index includes security note")
        _check(
            result,
            any("Agent Runtime" == item.get("title") for item in items),
            "index captures markdown titles",
        )
        _check_report_mentions(
            result,
            run_dir / "final_report.md",
            ["markdown_kb.py", "kb_index.json", "Model calls", "Tool calls"],
        )
    except Exception as exc:  # noqa: BLE001
        result.failures.append(str(exc))
    result.ok = not result.failures
    return result


def available_benchmark_ids() -> list[str]:
    return sorted(path.parent.name for path in (REPO_ROOT / "benchmarks").glob("*/benchmark.json"))


def _write_benchmark_verification_summary(workspace: Path) -> None:
    summary = {
        "schema_version": "0.1.0",
        "created_at": "2026-04-30T10:00:00+08:00",
        "status": "passed",
        "platform": "benchmark",
        "checks": [
            {"name": "run", "status": "passed", "summary": "benchmark run completed"},
            {"name": "compact", "status": "passed", "summary": "snapshot expected"},
            {"name": "handoff", "status": "passed", "summary": "handoff expected"},
        ],
        "artifacts": {},
    }
    JsonStore(SchemaValidator(REPO_ROOT / "schemas")).write(
        workspace / ".agent" / "verification" / "latest.json",
        summary,
        "verification_summary",
    )


def _manifest(benchmark_id: str) -> dict:
    return _read_json(REPO_ROOT / "benchmarks" / benchmark_id / "benchmark.json")


def _copy_fixtures(benchmark_id: str, workspace: Path) -> None:
    manifest = _manifest(benchmark_id)
    fixtures_dir = REPO_ROOT / "benchmarks" / benchmark_id / "fixtures"
    for fixture in manifest.get("fixtures", []):
        source = REPO_ROOT / "benchmarks" / benchmark_id / fixture
        target = workspace / source.relative_to(fixtures_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


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


def _extract_goal(prompt: str) -> str:
    marker = "User goal:"
    if marker not in prompt:
        return "offline benchmark goal"
    after_marker = prompt.split(marker, 1)[1]
    return after_marker.split("Project context:", 1)[0].strip() or "offline benchmark goal"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic agent runtime benchmarks.")
    parser.add_argument(
        "benchmarks",
        nargs="*",
        help="Benchmark ids to run; defaults to all MVP benchmarks.",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=None, help="Directory for benchmark workspaces"
    )
    parser.add_argument(
        "--keep-workspaces", action="store_true", help="Copy temp workspaces under .agent"
    )
    parser.add_argument("--list", action="store_true", help="List available benchmark ids and exit")
    args = parser.parse_args()

    if args.list:
        print("\n".join(available_benchmark_ids()))
        return 0

    results = run_benchmarks(
        benchmark_ids=args.benchmarks or None,
        work_dir=args.work_dir,
        keep_workspaces=args.keep_workspaces,
    )
    print(json.dumps([result.to_dict() for result in results], indent=2, ensure_ascii=False))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
