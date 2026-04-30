import json
from pathlib import Path


def test_mvp_benchmarks_are_declared() -> None:
    root = Path("benchmarks")
    manifests = sorted(root.glob("*/benchmark.json"))

    assert {path.parent.name for path in manifests} >= {
        "password_tool",
        "failing_tests_project",
        "compact_handoff",
    }

    for path in manifests:
        benchmark = json.loads(path.read_text(encoding="utf-8"))
        assert benchmark["schema_version"] == "0.1.0"
        assert benchmark["benchmark_id"] == path.parent.name
        assert benchmark["goal"]
        assert benchmark["expected_artifacts"]
        assert benchmark["acceptance"]
