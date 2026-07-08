from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.policy_config import load_policy_config, merge_policy_defaults
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator
from asteria_runtime.tools.command_tools import RunCommandTool

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
        score_text = (
            f"{overall['score']:.2f}   (graded on the real verification pass rate, not a status bucket)"
            if overall.get("score") is not None
            else "unverified (no executable verification ran)"
        )
        lines = [
            f"Correctness eval for run {self.run_id}",
            f"Status: {overall['status']}   Score: {score_text}",
            f"Verification commands: {signals['command_verification_pass_count']}"
            f"/{signals['command_verification_call_count']} passed"
            f" (rate {signals['command_verification_pass_rate']:.2f})",
            f"Task completion: {signals['task_completion_rate']:.2f}"
            f"   Blocked tasks: {signals['blocked_task_count']}",
            f"Reason: {overall['reason']}",
        ]
        rerun = self.report.get("rerun_eval")
        if isinstance(rerun, dict) and rerun.get("reran"):
            lines.append(
                f"Re-run (independent): {rerun['pass_count']}/{rerun['command_count']} "
                f"verification command(s) pass now (rate {rerun['pass_rate']:.2f})"
            )
            if rerun.get("divergence"):
                lines.append(
                    f"[!] DIVERGENCE: {len(rerun.get('divergent_commands') or [])} command(s) "
                    "recorded PASS but FAIL on re-run."
                )
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
    score = fraction of ``run_tests`` / ``run_command`` calls that actually passed. In read-only
    mode it touches no DO_NOT_TOUCH command. The report is written to
    ``run_dir/correctness_eval.json`` and validated against the ``eval_report`` schema
    (goal/artifact/trajectory/cost sections left empty on purpose — this is a correctness-only
    signal, not a full review).

    ``rerun=True`` (opt-in, default off) deepens the read-only signal into an INDEPENDENT one: it
    re-executes each recorded verification command against the CURRENT workspace through the same
    guarded ``RunCommandTool`` (ShellGuard + ADR-0020 env sanitization — no raw subprocess) and
    grades on the FRESH exit codes, flagging ``divergence`` when a recorded pass now fails (stale/
    broken/flaky artifact). Default off → byte-identical read-only behavior.
    """

    def __init__(self, root: Path, run_id: str | None = None, *, rerun: bool = False) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.rerun = rerun
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
        rerun_eval = self._rerun_signal(run_dir) if self.rerun else None
        report = self._report(run_id, signals, rerun_eval)
        report_path = run_dir / "correctness_eval.json"
        self.json_store.write(report_path, report, "eval_report")
        return CorrectnessEvalResult(run_id, report, report_path)

    def score_signal(self, run_dir: Path) -> dict | None:
        """Read-only graded correctness signal for ``run_dir`` (no persistence).

        Returns the graded ``{status, score, reason}`` derived from the REAL verification
        pass rate, or ``None`` when the run recorded no executable verification
        (``run_tests``/``run_command``) call — in that case there is no evidence to derive a
        real correctness score, so a caller must keep its own status-derived value rather than
        override a non-verification task (docs/creative) with a fabricated fail. Reused by the
        review pipeline to replace the 0.9/0.6/0.2 constant with the real signal.
        """
        signals = self._signals(run_dir)
        if signals["command_verification_call_count"] == 0:
            return None
        return self._grade(signals)

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

    def _rerun_signal(self, run_dir: Path) -> dict | None:
        """Re-execute each recorded verification command against the CURRENT workspace and grade on
        the fresh exit codes. Commands come from ``tool_observations.jsonl`` (the persisted
        ``observation.data.requested_command`` — structured, not summary-parsed) and run through the
        guarded ``RunCommandTool`` so ShellGuard + env sanitization apply exactly as at agent time.
        Returns ``None`` when the run recorded no verification command (nothing to independently
        confirm). Each unique command is re-run once (repair loops re-issue the same test)."""
        obs_path = run_dir / "tool_observations.jsonl"
        if not obs_path.exists():
            return None
        observations = self.jsonl.read_all(obs_path, None)
        commands: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for obs in observations:
            if obs.get("tool_name") not in VERIFICATION_TOOLS:
                continue
            data = (obs.get("observation") or {}).get("data") or {}
            command = str(data.get("requested_command") or data.get("command") or "").strip()
            if not command or command in seen:
                continue
            seen.add(command)
            recorded_ok = bool((obs.get("observation") or {}).get("ok", obs.get("ok")))
            commands.append((command, recorded_ok))
        if not commands:
            return None

        context = self._guarded_context(run_dir)
        tool = RunCommandTool()
        results: list[dict] = []
        passed = 0
        divergent: list[str] = []
        for command, recorded_ok in commands:
            try:
                outcome = tool.run(context, command)
                ok = bool(outcome.ok)
                returncode = (outcome.data or {}).get("returncode")
            except Exception as exc:  # noqa: BLE001 - a blocked/denied re-run is a fail, not a crash
                ok = False
                returncode = None
                results.append(
                    {
                        "command": command,
                        "ok": False,
                        "returncode": None,
                        "recorded_ok": recorded_ok,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
                if recorded_ok:
                    divergent.append(command)
                continue
            if ok:
                passed += 1
            elif recorded_ok:
                divergent.append(command)
            results.append(
                {
                    "command": command,
                    "ok": ok,
                    "returncode": returncode,
                    "recorded_ok": recorded_ok,
                }
            )
        count = len(commands)
        return {
            "reran": True,
            "command_count": count,
            "pass_count": passed,
            "pass_rate": round(passed / count, 4) if count else 0.0,
            "divergence": bool(divergent),
            "divergent_commands": divergent,
            "commands": results,
        }

    def _grade_rerun(self, rerun_eval: dict) -> dict:
        count = int(rerun_eval.get("command_count") or 0)
        rate = float(rerun_eval.get("pass_rate") or 0.0)
        divergence = bool(rerun_eval.get("divergence"))
        divergent = rerun_eval.get("divergent_commands") or []
        base = f"Re-ran {count} recorded verification command(s) against the current workspace"
        if rate >= 1.0 and not divergence:
            return {"status": "pass", "score": rate, "reason": f"{base}; all pass now."}
        reason = f"{base}; {rerun_eval.get('pass_count', 0)}/{count} pass now (rate {rate:.2f})."
        if divergence:
            reason += (
                f" DIVERGENCE: {len(divergent)} command(s) recorded PASS but FAIL on re-run "
                "(stale/broken/flaky artifact)."
            )
        return {"status": "fail" if rate <= 0.0 else "partial", "score": rate, "reason": reason}

    def _guarded_context(self, run_dir: Path) -> RuntimeContext:
        # Build a minimal context carrying the effective policy so re-run goes through the same
        # ShellGuard/env-sanitization boundary as agent-time execution (no raw subprocess). Fall back
        # to the default policy (which still carries the standard ShellGuard denylist) if the
        # workspace has no policies.json — re-run must stay guarded, never run unguarded or crash.
        try:
            policy = load_policy_config(self.root / ".asteria", self.validator)
        except (FileNotFoundError, SchemaValidationError):
            policy = merge_policy_defaults({})
        return RuntimeContext(
            root=self.root,
            run_id=self.run_id,
            policy=policy,
            validator=self.validator,
            run_dir_override=run_dir,
        )

    def _report(
        self, run_id: str | None, signals: dict, rerun_eval: dict | None = None
    ) -> dict:
        report = {
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
        # When re-run ran (opt-in), the FRESH exit codes are the stronger truth: surface the
        # independent signal and let `overall` reflect it (a recorded pass that now fails is a real
        # regression, not a stale claim to trust). `additionalProperties` is open on eval_report, so
        # this needs no schema change.
        if rerun_eval is not None:
            report["rerun_eval"] = rerun_eval
            report["overall"] = self._grade_rerun(rerun_eval)
        return report

    def _empty_signals(self) -> dict:
        return {
            "command_verification_call_count": 0,
            "command_verification_pass_count": 0,
            "command_verification_pass_rate": 0.0,
            "task_completion_rate": 0.0,
            "blocked_task_count": 0,
        }
