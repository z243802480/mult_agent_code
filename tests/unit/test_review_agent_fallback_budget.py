from __future__ import annotations

from pathlib import Path

from asteria_runtime.agents import review_agent as review_agent_module
from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse
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


def test_overall_uses_real_correctness_score_over_constant() -> None:
    agent = _agent()
    real = {"status": "partial", "score": 0.5, "reason": "2/4 verification passed"}

    # Model responded with a status but NO score -> the fabricated constant is replaced by the
    # real verification pass rate; the model's status is respected.
    model_no_score = agent._overall({"status": "pass"}, "pass", real)
    assert model_no_score["score"] == 0.5
    assert model_no_score["status"] == "pass"

    # Model supplied an explicit score -> that real judgment is kept (A1 only removes the constant).
    model_with_score = agent._overall({"status": "pass", "score": 0.95}, "pass", real)
    assert model_with_score["score"] == 0.95

    # Pure-deterministic review (model absent) -> the graded correctness verdict is authoritative.
    deterministic = agent._overall(None, "pass", real)
    assert deterministic == {"status": "partial", "score": 0.5, "reason": "2/4 verification passed"}

    # No verification evidence (correctness None) -> legacy constant preserved (reversible / no
    # fabricated fail against a non-verification task).
    assert agent._overall({"status": "pass"}, "pass", None)["score"] == 0.9
    assert agent._overall(None, "partial", None)["score"] == 0.6


def test_fallback_total_budget_seconds_parsing() -> None:
    agent = ReviewAgent(model_client=CountingFailingModel(), validator=SchemaValidator(Path("schemas")))
    assert agent._fallback_total_budget_seconds({}) == 120.0
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": 30}) == 30.0
    # Non-positive disables the cap; booleans fall back to the default.
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": 0}) is None
    assert agent._fallback_total_budget_seconds({"review_fallback_total_seconds": True}) == 120.0


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
