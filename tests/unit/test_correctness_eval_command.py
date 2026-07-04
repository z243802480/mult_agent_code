from pathlib import Path

from asteria_runtime.commands.correctness_eval_command import CorrectnessEvalCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator

SCHEMAS = Path("schemas")


def _make_run(
    tmp_path: Path,
    tool_calls: list[tuple[str, str]],
    tasks: list[str],
) -> str:
    validator = SchemaValidator(SCHEMAS)
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("execute")
    run_id = run["run_id"]
    run_dir = run_store.run_dir(run_id)
    jsonl = JsonlStore(validator)
    for index, (name, status) in enumerate(tool_calls):
        jsonl.append(
            run_dir / "tool_calls.jsonl",
            {
                "schema_version": "0.1.0",
                "tool_call_id": f"tc-{index}",
                "run_id": run_id,
                "tool_name": name,
                "input_summary": "cmd",
                "output_summary": "out",
                "status": status,
            },
            "tool_call",
        )
    JsonStore(validator).write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [{"task_id": f"t{i}", "status": s} for i, s in enumerate(tasks)],
        },
        "task_board",
    )
    return run_id


def test_score_is_graded_on_real_pass_rate_not_a_bucket(tmp_path: Path) -> None:
    run_id = _make_run(
        tmp_path,
        tool_calls=[("run_tests", "success"), ("run_tests", "success"), ("run_command", "failure")],
        tasks=["done", "done"],
    )

    result = CorrectnessEvalCommand(root=tmp_path, run_id=run_id).run()

    signals = result.report["outcome_eval"]
    assert signals["command_verification_call_count"] == 3
    assert signals["command_verification_pass_count"] == 2
    assert result.report["overall"]["status"] == "partial"
    # The whole point: a graded 2/3, NOT the old status-bucket constant 0.9.
    assert result.report["overall"]["score"] == round(2 / 3, 4)
    assert result.report["overall"]["score"] != 0.9
    # Artifact written and re-readable as an eval_report.
    report = JsonStore(SchemaValidator(SCHEMAS)).read(
        tmp_path / ".asteria" / "runs" / run_id / "correctness_eval.json", "eval_report"
    )
    assert report["overall"]["score"] == round(2 / 3, 4)


def test_all_verification_pass_and_done_is_pass(tmp_path: Path) -> None:
    run_id = _make_run(
        tmp_path,
        tool_calls=[("run_tests", "success"), ("run_command", "success")],
        tasks=["done"],
    )

    result = CorrectnessEvalCommand(root=tmp_path, run_id=run_id).run()

    assert result.report["overall"]["status"] == "pass"
    assert result.report["overall"]["score"] == 1.0


def test_no_executable_verification_is_fail_unproven(tmp_path: Path) -> None:
    # Files were written but nothing ran tests/commands -> correctness is unproven, not a pass.
    run_id = _make_run(
        tmp_path,
        tool_calls=[("write_file", "success"), ("read_file", "success")],
        tasks=["done"],
    )

    result = CorrectnessEvalCommand(root=tmp_path, run_id=run_id).run()

    assert result.report["overall"]["status"] == "fail"
    assert result.report["overall"]["score"] == 0.0
    assert "unproven" in result.report["overall"]["reason"]


def test_blocked_task_downgrades_full_pass_rate_to_partial(tmp_path: Path) -> None:
    run_id = _make_run(
        tmp_path,
        tool_calls=[("run_tests", "success")],
        tasks=["done", "blocked"],
    )

    result = CorrectnessEvalCommand(root=tmp_path, run_id=run_id).run()

    assert result.report["outcome_eval"]["blocked_task_count"] == 1
    assert result.report["overall"]["status"] == "partial"


def test_no_run_returns_empty_result(tmp_path: Path) -> None:
    result = CorrectnessEvalCommand(root=tmp_path).run()

    assert result.run_id is None
    assert result.report_path is None
    assert "no run found" in result.to_text().lower()


def test_score_signal_grades_real_rate_without_persisting(tmp_path: Path) -> None:
    # score_signal is the read-only reuse hook for the review pipeline: it grades on the real
    # pass rate and must NOT write correctness_eval.json (unlike run()).
    run_id = _make_run(
        tmp_path,
        tool_calls=[("run_tests", "success"), ("run_command", "failure")],
        tasks=["done"],
    )
    run_dir = tmp_path / ".asteria" / "runs" / run_id

    signal = CorrectnessEvalCommand(root=tmp_path).score_signal(run_dir)

    assert signal is not None
    assert signal["status"] == "partial"
    assert signal["score"] == round(1 / 2, 4)
    assert not (run_dir / "correctness_eval.json").exists()


def test_score_signal_is_none_without_executable_verification(tmp_path: Path) -> None:
    # No run_tests/run_command ran (docs/creative task): there is no real correctness evidence,
    # so the signal is None and the caller keeps its own status-derived score rather than being
    # forced to a fabricated fail.
    run_id = _make_run(
        tmp_path,
        tool_calls=[("write_file", "success")],
        tasks=["done"],
    )
    run_dir = tmp_path / ".asteria" / "runs" / run_id

    assert CorrectnessEvalCommand(root=tmp_path).score_signal(run_dir) is None
