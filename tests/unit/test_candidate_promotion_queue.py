import json
from pathlib import Path

from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_candidate_promotion_queue_records_auto_approved_and_promoted(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "source"
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    context = RuntimeContext(
        root=source,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=run_dir,
    )
    candidate = CandidateWorkspace.create(source, run_dir, "task-0001")
    queue = CandidatePromotionQueue(validator)

    promotion = queue.enqueue_auto_approved(
        context,
        task_id="task-0001",
        candidate=candidate,
        promotable_files=["tool.py"],
        merge_gate={"ok": True},
    )
    queue.mark_promoted(context, promotion, ["tool.py"])

    rows = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["status"] for row in rows] == ["auto_approved", "promoted"]
    assert rows[0]["promotion_id"] == rows[1]["promotion_id"]
    assert rows[0]["approval_mode"] == "auto"
    assert rows[1]["promoted_files"] == ["tool.py"]

    summary = queue.summary(run_dir)
    assert summary["total"] == 1
    assert summary["status_counts"] == {"promoted": 1}
    assert summary["promoted"][0]["promotion_id"] == rows[0]["promotion_id"]
    assert summary["pending"] == []
