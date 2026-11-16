import hashlib
import json
from pathlib import Path

import pytest

from asteria_runtime.core import review_focus as module
from asteria_runtime.core.context_slimming import project_review_evidence
from asteria_runtime.core.review_artifacts import collect_review_artifacts
from asteria_runtime.tools.file_tools import WriteFileTool
from tests.unit.test_review_artifacts import context


def write(ctx, text, number, task_id="active"):
    result = WriteFileTool().run(ctx, "result.custom", text, overwrite=True)
    assert result.ok
    return {"run_id": ctx.run_id, "task_id": task_id, "tool_call_id": f"call-{number}",
            "observation_id": f"obs-{number}", "tool_name": "write_file", "ok": True,
            "observation": {"data": result.data}}


def collect(ctx, observations, *, goal=None, board=None):
    goal = goal or {"target_outputs": ["result.custom"]}
    board = board or {"tasks": [{"task_id": "active", "acceptance": ["Preserve sign, not only magnitude"]}]}
    artifacts = collect_review_artifacts(ctx, goal, board)
    artifacts["review_focus"] = module.collect_review_focus(ctx, artifacts, goal, board, observations)
    ctx.validator.validate("review_artifacts", artifacts)
    return artifacts["review_focus"]


def test_diff_uses_first_recorded_active_backup_across_multiple_edits_and_is_read_only(tmp_path):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("value = original\n", encoding="utf8")
    first = write(ctx, "value = intermediate\n", 1)
    second = write(ctx, "value = current\n", 2)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    change = collect(ctx, [first, second])["changes"][0]
    assert change["status"] == "complete"
    assert "-value = original" in change["diff"] and "+value = current" in change["diff"]
    assert "intermediate" not in change["diff"]
    assert change["baseline"]["observation_id"] == "obs-1"
    captured = collect_review_artifacts(ctx, {"target_outputs": ["result.custom"]}, {})["files"][0]
    assert change["current_content_sha256"] == hashlib.sha256(captured["content"].encode("utf8")).hexdigest()
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_created_artifact_has_real_absent_baseline(tmp_path):
    ctx = context(tmp_path)
    change = collect(ctx, [write(ctx, "created\n", 1)])["changes"][0]
    assert change["baseline"]["existed"] is False
    assert "+created" in change["diff"] and change["status"] == "complete"


@pytest.mark.parametrize("mode", ["missing", "other_run", "discarded_task", "corrupt_first", "escaped_member"])
def test_unknown_baseline_never_rebases_onto_later_or_unrelated_evidence(tmp_path, mode):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("original\n", encoding="utf8")
    first, second = write(ctx, "intermediate\n", 1), write(ctx, "final\n", 2)
    observations = [first, second]
    if mode == "missing":
        observations = []
    elif mode == "other_run":
        observations = [{**row, "run_id": "other-run"} for row in observations]
    elif mode == "discarded_task":
        observations = [{**row, "task_id": "old"} for row in observations]
    else:
        folder = ctx.asteria_dir / "backups" / ctx.run_id / first["observation"]["data"]["backup_id"]
        path = folder / "manifest.json"
        if mode == "corrupt_first":
            path.write_text("{}", encoding="utf8")
        else:
            manifest = json.loads(path.read_text(encoding="utf8"))
            manifest["files"][0]["backup_path"] = "../../../../.env"
            path.write_text(json.dumps(manifest), encoding="utf8")
    change = collect(ctx, observations)["changes"][0]
    assert change["status"] == "unavailable" and change["diff"] is None and change["baseline"] is None
    assert change["reason"]


def test_linked_backup_is_rejected_without_reading_its_destination(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("original\n", encoding="utf8")
    observation = write(ctx, "current\n", 1)
    folder = ctx.asteria_dir / "backups" / ctx.run_id / observation["observation"]["data"]["backup_id"]
    backup = next((folder / "files").iterdir())
    target = tmp_path / "protected.key"
    target.write_bytes(backup.read_bytes())  # Same size: size alone is insufficient.
    backup.unlink()
    try:
        backup.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    original = Path.open
    def checked(path, *args, **kwargs):
        assert path.resolve() != target.resolve(), "Must not open linked private data"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", checked)
    assert collect(ctx, [observation])["changes"][0]["status"] == "unavailable"


def test_caps_and_unknown_semantic_coverage_keep_omissions_visible(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("before\n", encoding="utf8")
    observation = write(ctx, "changed " * 50, 1)
    monkeypatch.setattr(module, "MAX_DIFF_BYTES", 20)
    monkeypatch.setattr(module, "MAX_CRITERIA", 2)
    monkeypatch.setattr(module, "MAX_CRITERION_CHARS", 12)
    goal = {"target_outputs": ["result.custom"], "expanded_requirements": [
        {"description": "Preserve values and their signs", "acceptance": ["positive check passes", "negative check passes"]}]}
    focus = collect(ctx, [observation], goal=goal)
    assert focus["changes"][0]["status"] == "partial" and focus["changes"][0]["omitted_diff_bytes"] > 0
    assert len(focus["criteria"]) == 2 and focus["omitted_criteria"] == 2
    assert focus["criteria"][0]["truncated"]
    assert focus["criteria"][1]["source_ref"] == "goal_spec.expanded_requirements[0].acceptance[0]"
    assert focus["semantic_coverage"] == "unassessed"
    assert focus["task_evidence"][0]["relation"] == "same_task_only_not_criterion_coverage"


def test_projection_prioritizes_facts_without_changing_prompt_or_losing_unique_history(tmp_path):
    ctx = context(tmp_path)
    observation = write(ctx, "new\n", 1)
    focus = collect(ctx, [observation])
    payload = {"trajectory": {"unique_failure": "real historical failure"},
               "current_artifacts": {"files": ["retained full content"], "review_focus": focus},
               "goal_spec": {"original_goal": "the actual original request"}}
    before = json.dumps(payload, sort_keys=True)
    projected = project_review_evidence(payload)
    assert list(projected)[0] == "current_artifacts"
    assert list(projected["current_artifacts"])[0] == "review_focus"
    assert json.dumps(projected, sort_keys=True) == before and json.dumps(payload, sort_keys=True) == before
    assert project_review_evidence({"current_artifacts": None}) == {"current_artifacts": None}


def test_diff_focuses_actual_late_change_without_truncating_full_current_artifact(tmp_path):
    ctx = context(tmp_path)
    before = "".join(f"unchanged line {i}\n" for i in range(700))
    (tmp_path / "result.custom").write_text(before, encoding="utf8")
    lines = before.splitlines()
    lines[650] = "actual modified claim"
    observation = write(ctx, "\n".join(lines), 1)
    focus = collect(ctx, [observation])
    change = focus["changes"][0]
    assert "@@ -648,7 +648,7 @@" in change["diff"]
    assert "+actual modified claim" in change["diff"]
    assert change["status"] == "complete" and len(change["diff"]) < len(before)
    captured = collect_review_artifacts(ctx, {"target_outputs": ["result.custom"]}, {})
    assert captured["complete"] and len(captured["files"][0]["content"].splitlines()) == 700


@pytest.mark.parametrize("path", [".env", "../outside", ".asteria/private"])
def test_protected_targets_do_not_cause_internal_backup_reads(tmp_path, monkeypatch, path):
    ctx = context(tmp_path)
    observation = write(ctx, "normal content\n", 1)
    def forbidden(*args):
        raise AssertionError("Backup access is forbidden for protected/outside targets")
    monkeypatch.setattr(module, "_read_internal", forbidden)
    artifacts = {"files": [{"path": path, "status": "complete", "content": "untrusted supplied content",
                            "content_sha256": None}]}
    focus = module.collect_review_focus(ctx, artifacts, {}, {"tasks": [{"task_id": "active"}]}, [observation])
    assert focus["changes"][0]["status"] == "unavailable"


def test_oversize_baseline_and_partial_current_content_are_not_reported_as_unchanged(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("long baseline\n", encoding="utf8")
    observation = write(ctx, "current\n", 1)
    monkeypatch.setattr(module, "MAX_BASELINE_BYTES", 4)
    assert collect(ctx, [observation])["changes"][0]["diff"] is None
    partial = {"files": [{"path": "result.custom", "status": "partial", "content": "cur", "content_sha256": None}]}
    focus = module.collect_review_focus(ctx, partial, {}, {"tasks": [{"task_id": "active"}]}, [observation])
    assert focus["changes"][0]["status"] == "unavailable" and focus["changes"][0]["diff"] is None
