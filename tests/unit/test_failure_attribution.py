from __future__ import annotations

from agent_runtime.core.failure_attribution import classify_failure_attribution


def test_classifies_provider_transient_attempt() -> None:
    result = classify_failure_attribution(
        {
            "ok": False,
            "attempts": [{"failure_type": "timeout"}],
        }
    )

    assert result["category"] == "provider_transient"
    assert result["retryable"] is True


def test_classifies_legacy_recovery_failure() -> None:
    result = classify_failure_attribution(
        {
            "ok": False,
            "stderr_tail": "Real model smoke failed: recovery-resume failed with exit code 1.",
        }
    )

    assert result["category"] == "runtime_recovery_failed"


def test_classifies_invalid_json_model_output() -> None:
    result = classify_failure_attribution(
        {
            "ok": False,
            "failure_summary": "JSONDecodeError while parsing model response",
        }
    )

    assert result["category"] == "model_output_invalid_json"
