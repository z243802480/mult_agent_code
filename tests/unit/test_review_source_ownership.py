"""A task ID or duplicated receipt cannot borrow another source's evidence."""
from copy import deepcopy

import pytest

from asteria_runtime.core import review_focus
from tests.unit.test_review_artifacts import context
from tests.unit.test_review_focus import write, collect
from tests.unit.test_review_evidence import setup


def row(run, call, observation, task="active"):
    return {"run_id": run, "task_id": task, "tool_call_id": call, "observation_id": observation,
            "tool_name": "read_file", "ok": True, "observation": {"data": {}}}


def test_task_evidence_does_not_borrow_a_foreign_run_with_the_same_task_id(tmp_path):
    ctx = context(tmp_path)
    observations = [row(ctx.run_id, "own-call", "own-observation"), row("foreign", "foreign-call", "foreign-observation")]
    focus = review_focus.collect_review_focus(ctx, {"files": []}, {}, {"tasks": [{"task_id": "active"}]}, observations)
    assert focus["task_evidence"][0]["observation_ids"] == ["own-observation"]
    assert focus["semantic_coverage"] == "unassessed"


@pytest.mark.parametrize("kind", ["observation", "call", "missing_observation", "missing_call", "unbound_run"])
def test_ambiguous_or_unbound_observations_do_not_gain_task_evidence_links(tmp_path, kind):
    ctx = context(tmp_path)
    observations = [row(ctx.run_id, "call-a", "obs-a"), row(ctx.run_id, "call-b", "obs-b")]
    if kind == "observation":
        observations[1]["observation_id"] = "obs-a"
    elif kind == "call":
        observations[1]["tool_call_id"] = "call-a"
    elif kind == "missing_observation":
        observations[0].pop("observation_id")
    elif kind == "missing_call":
        observations[0].pop("tool_call_id")
    else:
        ctx.run_id = None
        for o in observations:
            o["run_id"] = None
    focus = review_focus.collect_review_focus(ctx, {"files": []}, {}, {"tasks": [{"task_id": "active"}]}, observations)
    expected = ["obs-b"] if kind.startswith("missing") else []
    assert focus["task_evidence"][0]["observation_ids"] == expected


def test_duplicate_task_identity_is_omitted_instead_of_selecting_an_owner(tmp_path):
    ctx = context(tmp_path)
    board = {"tasks": [{"task_id": "active"}, {"task_id": "active"}]}
    focus = review_focus.collect_review_focus(ctx, {"files": []}, {}, board, [row(ctx.run_id, "call-a", "obs-a")])
    assert focus["task_evidence"] == [] and focus["omitted_tasks"] == 2


def test_ambiguous_earliest_write_cannot_rebase_a_diff_on_a_later_valid_backup(tmp_path):
    ctx = context(tmp_path)
    (tmp_path / "result.custom").write_text("original\n", encoding="utf8")
    first = write(ctx, "intermediate\n", 1)
    duplicate = deepcopy(first)
    duplicate["tool_call_id"] = "different-call"
    last = write(ctx, "final\n", 2)
    focus = collect(ctx, [first, duplicate, last])
    assert focus["changes"][0]["status"] == "unavailable"
    assert focus["changes"][0]["diff"] is None
    assert focus["task_evidence"][0]["observation_ids"] == ["obs-2"]


def test_evidence_snapshot_rejects_duplicated_observation_identity_even_with_unique_calls(tmp_path):
    tools = setup(tmp_path)
    from asteria_runtime.core.review_evidence import ReviewEvidence
    observations = [row(tools.context.run_id, "call-a", "same-id", tools.task["task_id"]),
                    row(tools.context.run_id, "call-b", "same-id", tools.task["task_id"])]
    evidence = ReviewEvidence(tools.context, tools.artifacts["evidence_id"], tools.task["task_id"],
                              {"current_artifacts": {}}, observations, [], {"tasks": []})
    assert not any("/observation/" in ref for ref in evidence.sections)
    assert all("evidence_ref" not in o for o in evidence.origins["records"])
    tools.finish("completed")


def test_discarded_duplicate_cannot_supply_an_unambiguous_active_task_owner(tmp_path):
    ctx = context(tmp_path)
    board = {"tasks": [{"task_id": "active", "status": "done"},
                       {"task_id": "active", "status": "discarded"}]}
    focus = review_focus.collect_review_focus(ctx, {"files": []}, {}, board,
                                            [row(ctx.run_id, "call-a", "obs-a")])
    assert focus["task_evidence"] == [] and focus["omitted_tasks"] == 1
