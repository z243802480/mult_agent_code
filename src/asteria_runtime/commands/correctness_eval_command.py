from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"

# Tool calls whose real exit code is a code-correctness signal (subprocess ok/fail).
VERIFICATION_TOOLS = {"run_tests", "run_command"}


@dataclass(frozen=True)
class CorrectnessEvalResult:
    run_id: str | None
    report: dict
    report_path: Path | None

    def to_text(self) -> str:
        if self.run_id is None:
            return "Correctness eval: no run found. Run a goal first."
        overall = self.report["overall"]
        signals = self.report["outcome_eval"]
        lines = [
            f"Correctness eval for run {self.run_id}",
            f"Status: {overall['status']}   Score: {overall['score']:.2f}"
            "   (graded on the real verification pass rate, not a status bucket)",
            f"Verification commands: {signals['command_verification_pass_count']}"
            f"/{signals['command_verification_call_count']} passed"
            f" (rate {signals['command_verification_pass_rate']:.2f})",
            f"Task completion: {signals['task_completion_rate']:.2f}"
            f"   Blocked tasks: {signals['blocked_task_count']}",
            f"Reason: {overall['reason']}",
        ]
        if self.report_path is not None:
            lines.append(f"Report: {self.report_path}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return self.report


class CorrectnessEvalCommand:
    """Grade a run's correctness on the REAL verification pass rate.

    The existing review score (``eval_report.overall.score``) is a status-bucketed constant
    (0.9 / 0.6 / 0.2) that never consumes the real exit-code signal already captured in
    ``deterministic_checks.verification_pass_rate``. This command reads a run's persisted
    evidence (``tool_calls.jsonl`` + ``task_plan.json``) and emits a *graded* correctness
    score = fraction of ``run_tests`` / ``run_command`` calls that actually passed. It does
    not re-execute anything and touches no DO_NOT_TOUCH command. The report is written to
    ``run_dir/correctness_eval.json`` and validated against the ``eval_report`` schema
    (goal/artifact/trajectory/cost sections left empty on purpose — this is a correctness-only
    signal, not a full review).
    """

    def __init__(self, root: Path, run_id: str | None = None) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.validator = SchemaValidator(SCHEMA_DIR)
        self.json_store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.run_store = RunStore(self.root / ".asteria", self.validator)

    def run(self) -> CorrectnessEvalResult:
        run_id = self.run_id or self.run_store.latest_run_id()
        if run_id is None:
            return CorrectnessEvalResult(None, self._report(None, self._empty_signals()), None)
        run_dir = self.run_store.run_dir(run_id)
        signals = self._signals(run_dir)
        report = self._report(run_id, signals)
        report_path = run_dir / "correctness_eval.json"
        self.json_store.write(report_path, report, "eval_report")
        return CorrectnessEvalResult(run_id, report, report_path)

    def _signals(self, run_dir: Path) -> dict:
        # Read without schema validation: these rows were validated on write, and a graded
        # read-only signal must not crash on a legacy/edge record — it only needs name + status.
        tool_calls = self.jsonl.read_all(run_dir / "tool_calls.jsonl", None)
        command_calls = [c for c in tool_calls if c.get("tool_name") in VERIFICATION_TOOLS]
        passed = [c for c in command_calls if c.get("status") == "success"]

        tasks: list[dict] = []
        task_plan_path = run_dir / "task_plan.json"
        if task_plan_path.exists():
            task_plan = self.json_store.read(task_plan_path, "task_board")
            tasks = task_plan.get("tasks", [])
        active = [t for t in tasks if t.get("status") != "discarded"]
        done = [t for t in active if t.get("status") == "done"]
        blocked = [t for t in active if t.get("status") == "blocked"]

        return {
            "command_verification_call_count": len(command_calls),
            "command_verification_pass_count": len(passed),
            "command_verification_pass_rate": (
                len(passed) / len(command_calls) if command_calls else 0.0
            ),
            "task_completion_rate": (len(done) / len(active) if active else 0.0),
            "blocked_task_count": len(blocked),
        }

    def _grade(self, signals: dict) -> dict:
        calls = signals["command_verification_call_count"]
        rate = signals["command_verification_pass_rate"]
        blocked = signals["blocked_task_count"]
        completion = signals["task_completion_rate"]
        if calls == 0:
            return {
                "status": "fail",
                "score": 0.0,
                "reason": (
                    "No executable verification (run_tests/run_command) ran, so code "
                    "correctness is unproven."
                ),
            }
        score = round(rate, 4)
        if rate >= 1.0 and blocked == 0 and completion >= 1.0:
            return {
                "status": "pass",
                "score": score,
                "reason": f"All {calls} verification command(s) passed and no tasks are blocked.",
            }
        if rate <= 0.0:
            return {
                "status": "fail",
                "score": score,
                "reason": f"All {calls} verification command(s) failed.",
            }
        return {
            "status": "partial",
            "score": score,
            "reason": (
                f"{signals['command_verification_pass_count']}/{calls} verification command(s) "
                f"passed (rate {rate:.2f}); blocked tasks: {blocked}; "
                f"completion {completion:.2f}."
            ),
        }

    def _report(self, run_id: str | None, signals: dict) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "goal_eval": {},
            "artifact_eval": {},
            "outcome_eval": signals,
            "trajectory_eval": {},
            "cost_eval": {},
            "overall": (
                {"status": "fail", "score": 0.0, "reason": "No run found."}
                if run_id is None
                else self._grade(signals)
            ),
        }

    def _empty_signals(self) -> dict:
        return {
            "command_verification_call_count": 0,
            "command_verification_pass_count": 0,
            "command_verification_pass_rate": 0.0,
            "task_completion_rate": 0.0,
            "blocked_task_count": 0,
        }
