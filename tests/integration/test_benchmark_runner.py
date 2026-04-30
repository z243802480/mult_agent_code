from pathlib import Path

from scripts.run_benchmarks import run_benchmarks


def test_benchmark_runner_executes_mvp_benchmarks(tmp_path: Path) -> None:
    results = run_benchmarks(work_dir=tmp_path)

    assert {result.benchmark_id for result in results} == {
        "password_tool",
        "failing_tests_project",
        "compact_handoff",
    }
    assert all(result.ok for result in results), [result.to_dict() for result in results]
    assert (tmp_path / "password_tool" / "offline_artifact.txt").exists()
    assert (
        (tmp_path / "failing_tests_project" / "buggy_math.py")
        .read_text(encoding="utf-8")
        .strip()
        .endswith("a + b")
    )
    assert list((tmp_path / "compact_handoff" / ".agent" / "context" / "snapshots").glob("*.json"))
    assert list((tmp_path / "compact_handoff" / ".agent" / "context" / "handoffs").glob("*.json"))
