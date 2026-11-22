import hashlib
import os
from copy import deepcopy
from pathlib import Path

import pytest

from asteria_runtime.core.review_freshness import add_review_dependencies, review_freshness
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.json_store import JsonStore
from tests.helpers.review_binding import bind_fixture_review
from tests.unit.test_accept_command import _workspace_ready_for_accept


@pytest.fixture
def bound(tmp_path):
    root, run, _ = _workspace_ready_for_accept(tmp_path)
    validator = SchemaValidator(Path("schemas"))
    report = bind_fixture_review(root, run, validator)
    return root, run, validator, report


def test_unchanged_binding_is_current_and_mtime_is_not_a_version(bound):
    root, run, validator, report = bound
    os.utime(root / "tool.py", (1_700_000_000, 1_700_000_000))
    assert review_freshness(root, run, report, validator)["status"] == "current"


def test_same_size_and_mtime_content_change_is_stale_and_restoring_bytes_is_current(bound):
    root, run, validator, report = bound
    path = root / "tool.py"
    original, stat = path.read_bytes(), path.stat()
    path.write_bytes(original.replace(b"1", b"2"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert review_freshness(root, run, report, validator)["status"] == "changed"
    path.write_bytes(original)
    assert review_freshness(root, run, report, validator)["status"] == "current"


@pytest.mark.parametrize(
    "defect",
    [
        "unbound",
        "cross_run",
        "cross_snapshot",
        "duplicate",
        "omitted_artifact",
        "incomplete",
        "negative_bytes",
        "snapshot_missing",
        "protected",
        "traversal",
    ],
)
def test_invalid_or_unbound_inputs_cannot_approve_current_content(bound, defect):
    root, run, validator, report = bound
    binding = report["artifact_eval"]["review_binding"]
    if defect == "unbound":
        del report["artifact_eval"]["review_binding"]
    elif defect == "cross_run":
        binding["run_id"] = "run-other"
    elif defect == "cross_snapshot":
        binding["artifact_evidence_id"] = "review-artifacts-other"
    elif defect == "duplicate":
        binding["files"].append(dict(binding["files"][0]))
    elif defect == "omitted_artifact":
        binding["files"] = [r for r in binding["files"] if r["path"] != "tool.py"]
    elif defect == "incomplete":
        binding["complete"] = False
    elif defect == "negative_bytes":
        binding["files"][0]["bytes"] = -1
    elif defect == "snapshot_missing":
        (run / (binding["artifact_evidence_id"] + ".json")).unlink()
    else:
        binding["files"].append(
            {
                "root": "workspace",
                "path": ".env" if defect == "protected" else "../outside",
                "exists": False,
                "sha256": None,
                "bytes": 0,
            }
        )
    original = deepcopy(report)
    assert review_freshness(root, run, report, validator)["status"] != "current"
    assert report == original


def test_reused_validation_manifest_binds_checked_dependency_without_new_scan(bound):
    root, run, validator, report = bound
    path = root / "check.py"
    path.write_bytes(b"assert True\n")
    binding = report["artifact_eval"]["review_binding"]
    add_review_dependencies(
        binding,
        [
            {
                "path": "check.py",
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        ],
    )
    assert review_freshness(root, run, report, validator)["status"] == "current"
    path.write_bytes(b"assert None\n")
    assert review_freshness(root, run, report, validator)["status"] == "changed"


def test_absolute_artifact_paths_bind_to_workspace_relative_content(bound):
    root, run, validator, report = bound
    artifact_id = report["artifact_eval"]["review_binding"]["artifact_evidence_id"]
    store = JsonStore(validator)
    snapshot = store.read(run / (artifact_id + ".json"), "review_artifacts")
    snapshot["files"][0]["path"] = str(root / "tool.py")
    store.write(run / (artifact_id + ".json"), snapshot, "review_artifacts")
    assert review_freshness(root, run, report, validator)["status"] == "current"


def test_disappearance_between_snapshot_and_binding_cannot_be_recorded_as_current(bound):
    from asteria_runtime.core.review_freshness import capture_review_binding

    root, run, validator, report = bound
    store = JsonStore(validator)
    artifact_id = report["artifact_eval"]["review_binding"]["artifact_evidence_id"]
    snapshot = store.read(run / (artifact_id + ".json"), "review_artifacts")
    (root / "tool.py").unlink()
    binding = capture_review_binding(
        root,
        run,
        snapshot,
        [],
        goal=store.read(run / "goal_spec.json", "goal_spec"),
        board=store.read(run / "task_plan.json", "task_board"),
    )
    assert binding["complete"] is False


def test_binding_does_not_follow_a_replaced_file_link(bound):
    root, run, validator, report = bound
    outside = root.parent / "outside.txt"
    outside.write_text("same text is still a different boundary", encoding="utf8")
    path = root / "tool.py"
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not allow test symlinks")
    assert review_freshness(root, run, report, validator)["status"] != "current"
