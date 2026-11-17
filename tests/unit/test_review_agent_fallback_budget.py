from __future__ import annotations

from pathlib import Path
from hashlib import sha256

import pytest

from asteria_runtime.agents import review_agent as review_agent_module
from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class CountingFailingModel:
    """Records every chat attempt and always fails, forcing tier fallback."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover - raises
        self.calls.append(request.model_tier)
        raise RuntimeError("provider timed out")


def _review_context(**extra) -> dict:
    context = {
        "deterministic_checks": {
            "task_completion_rate": 0.0,
            "blocked_task_count": 0,
            "verification_pass_rate": 0.0,
        },
        "cost_report": {"status": "within_budget", "model_calls": 0, "tool_calls": 0},
    }
    context.update(extra)
    return context


def _agent() -> ReviewAgent:
    return ReviewAgent(
        model_client=CountingFailingModel(), validator=SchemaValidator(Path("schemas"))
    )


def test_overall_does_not_substitute_command_rate_for_model_score() -> None:
    agent = _agent()
    real = {"status": "partial", "score": 0.5, "reason": "2/4 verification passed"}

    # Missing semantic score remains unknown; the actual command rate is separate.
    model_no_score = agent._overall({"status": "pass"}, "pass", real)
    assert model_no_score["score"] is None
    assert model_no_score["score_source"] == "unassessed"
    assert model_no_score["status"] == "pass"

    # Model supplied an explicit score -> that real judgment is kept (A1 only removes the constant).
    model_with_score = agent._overall({"status": "pass", "score": 0.95}, "pass", real)
    assert model_with_score["score"] == 0.95

    # Missing semantic judgment remains unavailable even with measured execution results.
    deterministic = agent._overall(None, "pass", real)
    assert deterministic["status"] == "partial"
    assert deterministic["score"] is None
    assert "unavailable" in deterministic["reason"]
    assert "do not establish artifact or requirement coverage" in deterministic["reason"]

    # No numeric model score does not invent a new approval policy or runtime score.
    unverified_model = agent._overall({"status": "pass"}, "pass", None)
    assert unverified_model["score"] is None
    assert unverified_model["status"] == "pass"
    assert "unassessed" in unverified_model["reason"].lower()
    unverified_deterministic = agent._overall(None, "partial", None)
    assert unverified_deterministic["score"] is None
    assert "unavailable" in unverified_deterministic["reason"].lower()


def test_fallback_total_budget_seconds_parsing() -> None:
    agent = ReviewAgent(model_client=CountingFailingModel(), validator=SchemaValidator(Path("schemas")))
    assert agent._fallback_total_budget_seconds({}) == 120.0
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": 30}) == 30.0
    # Non-positive disables the cap; booleans fall back to the default.
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": 0}) is None
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": True}) == 120.0


@pytest.mark.parametrize("content", ["not JSON", "{}", '{"overall":{"status":"unknown"}}', "x" * 25000])
def test_missing_semantic_judgment_never_promotes_green_execution_checks(content):
    class InvalidReviewer:
        calls = 0
        def chat(self, request):
            self.calls += 1
            return ChatResponse(content=content, finish_reason="stop", usage=TokenUsage(1, 1, 2),
                                model_provider="fake", model_name="invalid-review-fixture", raw_response={})
    client = InvalidReviewer()
    agent = ReviewAgent(client, SchemaValidator(Path("schemas")))
    report = agent.evaluate(_review_context(
        deterministic_checks={"task_completion_rate": 1.0, "blocked_task_count": 0, "verification_pass_rate": 1.0},
        correctness_signal={"status": "pass", "score": 1.0, "reason": "All commands passed"},
    ), "run-unavailable-review")
    assert client.calls == 2
    assert report["overall"]["status"] == "partial" and report["overall"]["score"] is None
    assert report["goal_eval"]["requirement_coverage"] is None
    assert len(report["trajectory_eval"]["review_protocol_errors"]) == 2
    assert report["trajectory_eval"]["review_protocol_recovery"]["recovered"] is False
    error = report["trajectory_eval"]["review_protocol_errors"][0]
    assert error["response_excerpt"] == content[:24000]
    assert error["response_chars"] == len(content)
    assert error["response_excerpt_truncated"] is (len(content) > 24000)


def test_review_protocol_correction_preserves_evidence_and_call_limits():
    original = '{"status":"partial","finding":"Requested output differs from current artifact"}'
    class CorrectingReviewer:
        requests = None
        def __init__(self):
            self.requests = []
        def chat(self, request):
            self.requests.append(request)
            content = original if len(self.requests) == 1 else (
                '{"overall":{"status":"partial","score":0.6,"reason":"Requested output differs from current artifact"}}'
            )
            return ChatResponse(content=content, finish_reason="length" if len(self.requests) == 1 else "stop",
                                usage=TokenUsage(1, 1, 2), model_provider="fake",
                                model_name="protocol-fixture", raw_response={})
    client = CorrectingReviewer()
    report = ReviewAgent(client, SchemaValidator(Path("schemas"))).evaluate(_review_context(), "run-correction")
    assert report["overall"]["status"] == "partial"
    assert report["trajectory_eval"]["review_assessment"]["status"] == "assessed"
    error = report["trajectory_eval"]["review_protocol_errors"][0]
    assert error["response_excerpt"] == original
    assert error["response_sha256"] == sha256(original.encode("utf8")).hexdigest()
    assert error["finish_reason"] == "length" and not error["response_excerpt_truncated"]
    assert report["trajectory_eval"]["review_protocol_recovery"] == {
        "attempts": 2, "recovered": True, "skipped_reason": None,
    }
    assert len(client.requests) == 2
    first, second = client.requests
    assert second.messages[:len(first.messages)] == first.messages
    assert second.messages[-2].content == original
    assert "Preserve your substantive findings" in second.messages[-1].content
    assert second.max_output_tokens == first.max_output_tokens == 5000
    assert second.model_tier == first.model_tier and second.metadata == first.metadata


def test_review_protocol_correction_stops_when_time_budget_spent(monkeypatch):
    class InvalidReviewer:
        calls = 0
        def chat(self, request):
            self.calls += 1
            return ChatResponse(content="", finish_reason="length", usage=TokenUsage(1, 1, 2),
                                model_provider="fake", model_name="invalid-review-fixture", raw_response={})
    client = InvalidReviewer()
    clock = iter([0.0, 130.0])
    monkeypatch.setattr(review_agent_module.time, "monotonic", lambda: next(clock))
    report = ReviewAgent(client, SchemaValidator(Path("schemas"))).evaluate(_review_context(), "run-spent")
    assert client.calls == 1 and report["overall"]["score"] is None
    assert report["trajectory_eval"]["review_assessment"]["reason"] == "invalid_json"
    assert report["trajectory_eval"]["review_protocol_recovery"] == {
        "attempts": 1, "recovered": False, "skipped_reason": "time_budget_exhausted",
    }


def test_review_fallback_stops_after_budget_exceeded(monkeypatch) -> None:
    model = CountingFailingModel()
    agent = ReviewAgent(model_client=model, validator=SchemaValidator(Path("schemas")))

    # review_started=0.0, then the next clock read (before the 2nd tier) is past budget.
    clock = iter([0.0, 100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(review_agent_module.time, "monotonic", lambda: next(clock))

    report = agent.evaluate(_review_context(review_fallback_total_seconds=5), run_id="run-budget")

    # Only the first (strong) tier was attempted; medium/cheap were skipped once the
    # cumulative budget was spent rather than chasing more provider timeouts.
    assert model.calls == ["strong"]
    fallback = report["trajectory_eval"]["review_fallback"]
    assert fallback["used"] is True
    assert fallback["source"] == "deterministic_checks"
    assert "ReviewFallbackBudgetExceeded" in {
        item["error_type"] for item in report["trajectory_eval"]["review_model_call_errors"]
    }


def test_review_fallback_tries_all_tiers_when_budget_not_exceeded(monkeypatch) -> None:
    model = CountingFailingModel()
    agent = ReviewAgent(model_client=model, validator=SchemaValidator(Path("schemas")))

    # Clock never advances, so the budget never trips and every tier is attempted.
    monkeypatch.setattr(review_agent_module.time, "monotonic", lambda: 0.0)

    agent.evaluate(_review_context(review_fallback_total_seconds=5), run_id="run-all-tiers")

    assert model.calls == ["strong", "medium", "cheap"]
