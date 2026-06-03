from __future__ import annotations

from typing import Any


def capability_feedback_active_next_step(feedback: dict[str, Any]) -> str:
    """Return the product-facing next step for capability feedback.

    Raw capability feedback can include historical or maintainer-oriented actions. The
    default user surface should show the active recovery step instead of replaying old
    route noise.
    """

    explicit = str(feedback.get("active_next_step") or "").strip()
    if explicit:
        return explicit
    decision = str(feedback.get("decision") or "")
    if decision == "retry_or_downgrade":
        return (
            "Keep strong goal_spec on retry/downgrade guard; rerun one small validation "
            "sample before widening."
        )
    if decision == "escalated_to_strong":
        matched = feedback.get("matched_route")
        matched = matched if isinstance(matched, dict) else {}
        purpose = str(matched.get("purpose") or "affected route")
        tier = str(matched.get("model_tier") or "selected route")
        return (
            f"Use the selected stronger route for {purpose}/{tier}; review results before scaling."
        )
    if decision == "downgraded_for_low_risk":
        return "Use the selected cheaper route for this low-risk task; verify before widening."
    if decision == "no_escalation":
        return "Continue with the selected route and keep collecting capability evidence."
    actions = [str(item) for item in feedback.get("recommended_actions") or [] if item]
    for action in actions:
        if _looks_historical_or_overbroad(action):
            continue
        return action
    status = str(feedback.get("status") or "healthy")
    if status == "blocked":
        return "Repair active route evidence before widening scope."
    if status == "review":
        return "Review active route evidence before widening scope."
    return "Continue with the selected route and keep collecting capability evidence."


def _looks_historical_or_overbroad(action: str) -> bool:
    text = action.lower()
    return (
        "pause scaling affected routes" in text
        or "collect fresh route evidence" in text
        or "stale route guidance" in text
    )
