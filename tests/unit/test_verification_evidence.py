from asteria_runtime.evaluation.verification_evidence import (
    discarded_task_ids,
    final_round_verification,
)


def test_missing_task_ids_cannot_hide_an_unattributed_failure() -> None:
    failure = {"ok": False, "data": {"command": "test failing"}}
    success = {"ok": True, "data": {"command": "test passing"}}
    evidence = [
        {"verification_results": [failure]},
        {"task_id": "", "verification_results": [success]},
    ]
    discarded = discarded_task_ids([{"status": "discarded"}])

    assert discarded == set()
    assert final_round_verification(evidence, discarded_ids=discarded) == [failure, success]


def test_explicit_empty_round_supersedes_an_earlier_pass() -> None:
    evidence = [
        {"task_id": "t1", "verification_results": [{"ok": True}]},
        {"task_id": "t1", "verification_results": []},
    ]

    assert final_round_verification(evidence) == []
    assert final_round_verification([{"task_id": "legacy"}]) is None
