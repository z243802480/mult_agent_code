from pathlib import Path

import pytest

from scripts.run_benchmarks import run_benchmarks

# RA7b slice3e: the whole benchmark runner now runs on the model-driven spine default.
# `failing_tests_project` asserts spine-native recovery evidence (correctness-gate rejection of the
# failing baseline + repaired-then-done task_execution_evidence) instead of FSM candidate-discard /
# experiments.jsonl; the file_renamer/markdown_kb fakes emit the spine JSON turn contract via
# _spine_from_execution_action. This unpins the last FSM-only benchmark test.
pytestmark = pytest.mark.spine_default


def test_benchmark_runner_executes_mvp_benchmarks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")
    results = run_benchmarks(work_dir=tmp_path)

    assert {result.benchmark_id for result in results} == {
        "password_tool",
        "failing_tests_project",
        "compact_handoff",
        "file_renamer",
        "markdown_kb",
    }
    assert all(result.ok for result in results), [result.to_dict() for result in results]
    assert (tmp_path / "password_tool" / "offline_artifact.txt").exists()
    assert (
        (tmp_path / "failing_tests_project" / "buggy_math.py")
        .read_text(encoding="utf-8")
        .strip()
        .endswith("a + b")
    )
    assert list(
        (tmp_path / "compact_handoff" / ".asteria" / "context" / "snapshots").glob("*.json")
    )
    assert list((tmp_path / "compact_handoff" / ".asteria" / "context" / "handoffs").glob("*.json"))
    assert (tmp_path / "file_renamer" / "rename_plan.json").exists()
    assert (tmp_path / "file_renamer" / "IMG_0001.txt").exists()
    assert not (tmp_path / "file_renamer" / "photo-0001.txt").exists()
    assert (tmp_path / "markdown_kb" / "markdown_kb.py").exists()
    assert (tmp_path / "markdown_kb" / "kb_index.json").exists()
    assert (tmp_path / "markdown_kb" / "notes" / "asteria_runtime.md").exists()
