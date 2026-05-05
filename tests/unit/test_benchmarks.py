import json
from pathlib import Path

from scripts.run_benchmarks import available_benchmark_ids


def test_mvp_benchmarks_are_declared() -> None:
    root = Path("benchmarks")
    manifests = sorted(root.glob("*/benchmark.json"))

    assert {path.parent.name for path in manifests} >= {
        "password_tool",
        "failing_tests_project",
        "compact_handoff",
        "file_renamer",
    }

    for path in manifests:
        benchmark = json.loads(path.read_text(encoding="utf-8"))
        assert benchmark["schema_version"] == "0.1.0"
        assert benchmark["benchmark_id"] == path.parent.name
        assert benchmark["goal"]
        assert benchmark["expected_artifacts"]
        assert benchmark["acceptance"]


def test_benchmark_runner_discovers_declared_benchmarks() -> None:
    assert set(available_benchmark_ids()) >= {
        "password_tool",
        "failing_tests_project",
        "compact_handoff",
        "file_renamer",
    }
