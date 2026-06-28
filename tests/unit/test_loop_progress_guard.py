from __future__ import annotations

from asteria_runtime.core.loop_progress_guard import (
    evaluate_loop_quality,
    observation_progress_fingerprint,
)


def _obs(status: str, summary: str, *, refs: list[str] | None = None) -> dict:
    return {
        "observation_type": "tool_result",
        "status": status,
        "summary": summary,
        "evidence_refs": refs or [],
    }


def test_empty_history_is_ok_without_warning() -> None:
    signal = evaluate_loop_quality([])
    assert signal is not None
    assert signal["warn"] is False
    assert signal["severity"] == "ok"
    assert signal["repeated_failed_verifications"] == 0


def test_three_consecutive_failures_trip_default_failed_window() -> None:
    history = [
        _obs("failed", "verification failed: greet.py missing"),
        _obs("failed", "verification failed: greet.py missing"),
        _obs("failed", "verification failed: greet.py missing"),
    ]
    signal = evaluate_loop_quality(history)
    assert signal["warn"] is True
    assert signal["repeated_failed_verifications"] == 3
    assert signal["hard_block"] is False
    assert "consecutive failed verifications" in signal["reason"]


def test_progress_between_failures_resets_failed_run() -> None:
    history = [
        _obs("failed", "attempt 1 failed"),
        _obs("succeeded", "wrote greet.py"),
        _obs("failed", "attempt 3 failed"),
    ]
    signal = evaluate_loop_quality(history)
    # Only the trailing single failure counts; the success broke the run.
    assert signal["repeated_failed_verifications"] == 1
    assert signal["warn"] is False


def test_volatile_execution_ids_do_not_count_as_progress() -> None:
    # Same work, only the per-round execution/decision id differs -> identical fingerprint.
    a = _obs("failed", "same failure", refs=["agent-loop-execution-0001"])
    b = _obs("failed", "same failure", refs=["agent-loop-execution-0002"])
    assert observation_progress_fingerprint(a) == observation_progress_fingerprint(b)


def test_new_artifact_breaks_identical_fingerprint() -> None:
    a = _obs("failed", "same failure", refs=["validation:check-1"])
    b = _obs("failed", "same failure", refs=["validation:check-1", "changed:greet.py"])
    assert observation_progress_fingerprint(a) != observation_progress_fingerprint(b)


def test_repeated_identical_window_trips_with_enough_repeats() -> None:
    history = [_obs("failed", "same failure") for _ in range(8)]
    signal = evaluate_loop_quality(history, config={"repeated_identical_tool_window": 8})
    assert signal["repeated_identical_observations"] == 8
    assert signal["warn"] is True
    assert "identical no-progress" in signal["reason"]


def test_custom_window_overrides_default() -> None:
    history = [_obs("failed", "f"), _obs("failed", "f")]
    signal = evaluate_loop_quality(history, config={"repeated_failed_verification_window": 2})
    assert signal["repeated_failed_window"] == 2
    assert signal["warn"] is True


def test_disabled_guard_returns_none() -> None:
    assert evaluate_loop_quality([_obs("failed", "f")], config={"enabled": False}) is None


def test_single_observation_is_not_a_repeat() -> None:
    signal = evaluate_loop_quality([_obs("failed", "only one")])
    assert signal["repeated_identical_observations"] == 0
    assert signal["repeated_failed_verifications"] == 1
    assert signal["warn"] is False
