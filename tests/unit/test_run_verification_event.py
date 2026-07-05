"""RunCommand surfaces the real executable-verification verdict as a user_progress event.

The Studio thread tails user_progress.jsonl, so emitting a `verification` event is what makes the
"did the code actually pass?" verdict visible to a UX user (not just "completed"). The signal is
read-only (CorrectnessEvalCommand.score_signal reads recorded run_tests/run_command exit codes).
"""
import json
from pathlib import Path

from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


def _run_dir(root: Path, run_id: str) -> Path:
    d = root / ".asteria" / "runs" / run_id
    d.mkdir(parents=True)
    return d


def _write_tool_calls(run_dir: Path, calls: list[dict]) -> None:
    (run_dir / "tool_calls.jsonl").write_text(
        "\n".join(json.dumps(c) for c in calls) + "\n", encoding="utf-8"
    )


def _emit(root: Path, run_id: str) -> tuple[dict | None, list[dict]]:
    validator = SchemaValidator(Path.cwd() / "schemas")
    log = root / ".asteria" / "runs" / run_id / "user_progress.jsonl"
    progress = UserProgressLogger(log, validator)
    signal = RunCommand(root=root)._emit_correctness_verification(progress, run_id)
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return signal, events


def test_passing_verification_emits_pass_event(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run-1")
    _write_tool_calls(rd, [{"tool_name": "run_tests", "status": "success"}])
    # A green verdict needs full task completion too (mirrors the real ignition run).
    (rd / "task_plan.json").write_text(
        json.dumps({"schema_version": "0.1.0", "tasks": [{"status": "done"}]}), encoding="utf-8"
    )
    signal, events = _emit(tmp_path, "run-1")
    assert signal == {"status": "pass", "score": 1.0, "reason": signal["reason"]}
    ev = events[-1]
    assert ev["transcript_kind"] == "verification"
    assert ev["status"] == "completed"
    assert "通过" in ev["title"]
    assert ev["data"]["correctness"]["score"] == 1.0
    assert ev["telemetry"]["correctness_status"] == "pass"


def test_failing_verification_emits_failed_event(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run-2")
    _write_tool_calls(rd, [{"tool_name": "run_command", "status": "error"}])
    signal, events = _emit(tmp_path, "run-2")
    assert signal is not None and signal["status"] == "fail"
    ev = events[-1]
    assert ev["transcript_kind"] == "verification"
    assert ev["status"] == "failed"  # a non-green verdict is not dressed up as completed
    assert "未通过" in ev["title"]


def test_no_executable_verification_is_honest_not_a_fake_pass(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run-3")
    # Only non-verification tools ran (write_file); there is nothing to prove correctness.
    _write_tool_calls(rd, [{"tool_name": "write_file", "status": "success"}])
    signal, events = _emit(tmp_path, "run-3")
    assert signal is None  # honest: no fabricated pass
    ev = events[-1]
    assert ev["transcript_kind"] == "verification"
    assert "未运行" in ev["title"]
    assert ev["data"]["correctness"] is None
    # Every graded verdict outcome carries the machine discriminator so the Studio thread can tell
    # it apart from generic review-phase "verification" steps (which never set it).
    assert ev["telemetry"]["correctness_status"] == "unrun"


def test_missing_run_dir_never_aborts(tmp_path: Path) -> None:
    # Best-effort: a missing/broken run dir must not raise out of the helper.
    (tmp_path / ".asteria" / "runs" / "run-4").mkdir(parents=True)
    signal, events = _emit(tmp_path, "run-4")
    assert signal is None
    assert events[-1]["transcript_kind"] == "verification"
