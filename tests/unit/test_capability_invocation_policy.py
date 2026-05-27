from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy


def test_capability_invocation_policy_keeps_ordinary_chat_lightweight() -> None:
    policy = CapabilityInvocationPolicy().for_intent("ordinary_chat")

    assert policy["intent"] == "ordinary_chat"
    assert policy["allow_tools"] is False
    assert policy["allow_mcp"] is False
    assert policy["allow_skills"] is False
    assert policy["allowed_capability_groups"] == []


def test_capability_invocation_policy_mounts_runtime_groups_for_progress() -> None:
    policy = CapabilityInvocationPolicy().for_intent("next_step_question")

    assert policy["allow_tools"] is False
    assert "runtime_status" in policy["allowed_capability_groups"]
    assert "goal_memory" in policy["allowed_capability_groups"]
