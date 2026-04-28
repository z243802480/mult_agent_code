from agent_runtime.core.decision_policy import DecisionPolicy


def policy(granularity: str = "balanced") -> dict:
    return {"decision_granularity": granularity}


def test_balanced_policy_escalates_high_impact_follow_up() -> None:
    follow_up = {
        "title": "Add online breach API",
        "description": "Use an external API to check leaked passwords.",
        "impact": {"scope": "medium", "budget": "low", "risk": "high", "quality": "high"},
    }

    candidate = DecisionPolicy(policy()).candidate_for_follow_up(follow_up)

    assert candidate is not None
    assert candidate.impact["risk"] == "high"
    assert [option["option_id"] for option in candidate.options] == ["approve", "defer"]


def test_balanced_policy_keeps_routine_follow_up_autonomous() -> None:
    follow_up = {
        "title": "Add README helper",
        "description": "Create a small README helper artifact.",
        "category": "implementation",
        "impact": {"scope": "low", "budget": "low", "risk": "low", "quality": "medium"},
    }

    assert DecisionPolicy(policy()).candidate_for_follow_up(follow_up) is None


def test_manual_policy_escalates_every_follow_up() -> None:
    follow_up = {"title": "Add docs", "description": "Add short usage docs."}

    assert DecisionPolicy(policy("manual")).candidate_for_follow_up(follow_up) is not None
