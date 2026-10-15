from __future__ import annotations

import json

import pytest

from scripts.nightly_release_proof import classify_ring_proof, classify_studio_proof, main


def _jobs(*, job_result: str = "success", smoke_result: str = "success") -> dict:
    return {
        "jobs": [
            {
                "name": "studio-real-model-nightly",
                "conclusion": job_result,
                "steps": [
                    {"name": "Check real-model secret", "conclusion": "success"},
                    {"name": "Studio real-model smokes", "conclusion": smoke_result},
                    {
                        "name": "Record missing-key status",
                        "conclusion": "success" if smoke_result == "skipped" else "skipped",
                    },
                ],
            }
        ]
    }


def test_green_job_with_skipped_smokes_is_not_model_proof() -> None:
    # Shape observed in Actions run 38676431024: the job is green because its NOT RUN summary passed.
    status, _ = classify_studio_proof(
        {"url": "https://example.test/run"}, _jobs(smoke_result="skipped")
    )
    assert status == "NOT RUN"


def test_only_executed_successful_smokes_are_proof() -> None:
    status, _ = classify_studio_proof({}, _jobs())
    assert status == "NEVER RUN"
    status, _ = classify_studio_proof({"url": "https://example.test/run"}, _jobs())
    assert status == "PASSED"


def test_failure_and_old_nightly_are_reported_without_promotion_to_pass() -> None:
    run = {"url": "https://example.test/run"}
    assert (
        classify_studio_proof(run, _jobs(job_result="failure", smoke_result="failure"))[0]
        == "FAILED"
    )
    assert classify_studio_proof(run, {"jobs": []})[0] == "NEVER RUN"
    assert classify_studio_proof(run, {})[0] == "UNKNOWN"


def test_green_ring_job_with_skipped_model_step_is_not_runtime_proof() -> None:
    # Shape observed in ring-recovery run 38639068136.
    run = {"conclusion": "success"}
    jobs = {
        "jobs": [
            {
                "name": "ring-recovery",
                "conclusion": "success",
                "steps": [
                    {"name": "Check real-provider secrets", "conclusion": "success"},
                    {
                        "name": "Ring recovery (full RunCommand end-to-end, real stack)",
                        "conclusion": "skipped",
                    },
                ],
            }
        ]
    }
    assert classify_ring_proof(run, jobs)[0] == "NOT RUN"
    jobs["jobs"][0]["steps"][1]["conclusion"] = "success"
    assert classify_ring_proof(run, jobs)[0] == "PASSED"
    jobs["jobs"][0]["steps"][1]["conclusion"] = "failure"
    jobs["jobs"][0]["conclusion"] = "failure"
    assert classify_ring_proof(run, jobs)[0] == "FAILED"


def test_failed_ring_step_still_blocks_release(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("PROOF_KIND", "ring")
    monkeypatch.setenv("RUN_JSON", json.dumps([{"conclusion": "failure"}]))
    monkeypatch.setenv(
        "JOBS_JSON",
        json.dumps(
            {
                "jobs": [
                    {
                        "name": "ring-recovery",
                        "conclusion": "failure",
                        "steps": [
                            {
                                "name": "Ring recovery (full RunCommand end-to-end, real stack)",
                                "conclusion": "failure",
                            }
                        ],
                    }
                ]
            }
        ),
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "**FAILED**" in summary.read_text(encoding="utf-8")


def test_run_lookup_failure_is_unknown_not_never_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("PROOF_KIND", "studio")
    monkeypatch.setenv("RUN_JSON", "null")
    monkeypatch.setenv("JOBS_JSON", "{}")
    main()
    assert "**UNKNOWN**" in summary.read_text(encoding="utf-8")
