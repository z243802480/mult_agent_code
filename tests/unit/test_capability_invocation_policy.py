from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy


def test_capability_invocation_policy_keeps_ordinary_chat_lightweight() -> None:
    policy = CapabilityInvocationPolicy().for_intent("ordinary_chat")

    assert policy["intent"] == "ordinary_chat"
    assert policy["task_kind"] == "chat"
    assert policy["allow_tools"] is False
    assert policy["allow_mcp"] is False
    assert policy["allow_skills"] is False
    assert policy["allowed_capability_groups"] == []


def test_capability_invocation_policy_mounts_runtime_groups_for_progress() -> None:
    policy = CapabilityInvocationPolicy().for_intent("next_step_question")

    assert policy["allow_tools"] is False
    assert "runtime_status" in policy["allowed_capability_groups"]
    assert "goal_memory" in policy["allowed_capability_groups"]


def test_capability_invocation_policy_allows_controlled_implementation_tools() -> None:
    policy = CapabilityInvocationPolicy().for_goal(
        "implementation_goal",
        permission_mode="reviewed_auto",
        risk="medium",
    )

    assert policy["allow_tools"] is True
    assert policy["tool_permissions"]["read"] == "allow"
    assert policy["tool_permissions"]["write"] == "ask"
    assert policy["tool_permissions"]["execute"] == "ask"
    assert policy["mcp_permission"] == "ask"


def test_capability_invocation_policy_limits_brainstorm_to_read_only_tools() -> None:
    read_decision = CapabilityInvocationPolicy().for_tool(
        "search_text",
        intent="brainstorm_goal",
        task_kind="brainstorm",
        permission_mode="auto",
        risk="low",
    )
    write_decision = CapabilityInvocationPolicy().for_tool(
        "write_file",
        intent="brainstorm_goal",
        task_kind="brainstorm",
        permission_mode="auto",
        risk="low",
    )

    assert read_decision["decision"] == "allow"
    assert write_decision["decision"] == "deny"
    assert write_decision["allowed"] is False


def test_capability_invocation_policy_allows_readonly_research_commands_with_decision() -> None:
    command_decision = CapabilityInvocationPolicy().for_tool(
        "run_command",
        intent="research_goal",
        task_kind="research",
        permission_mode="reviewed_auto",
        risk="low",
    )
    write_decision = CapabilityInvocationPolicy().for_tool(
        "write_file",
        intent="research_goal",
        task_kind="research",
        permission_mode="reviewed_auto",
        risk="low",
    )

    assert command_decision["decision"] == "ask"
    assert command_decision["requires_decision"] is True
    assert write_decision["decision"] == "deny"


def test_capability_invocation_policy_enables_matching_artifact_skill_only() -> None:
    documents = CapabilityInvocationPolicy().for_tool(
        "documents",
        intent="document_goal",
        task_kind="document",
        permission_mode="reviewed_auto",
        risk="medium",
        capability_type="skill",
    )
    spreadsheets = CapabilityInvocationPolicy().for_tool(
        "spreadsheets",
        intent="document_goal",
        task_kind="document",
        permission_mode="reviewed_auto",
        risk="medium",
        capability_type="skill",
    )

    assert documents["decision"] == "allow"
    assert spreadsheets["decision"] == "deny"


def test_capability_invocation_policy_high_risk_mcp_requires_decision() -> None:
    decision = CapabilityInvocationPolicy().for_tool(
        "mcp",
        intent="research_goal",
        task_kind="research",
        permission_mode="auto",
        risk="high",
        capability_type="mcp",
    )

    assert decision["decision"] == "ask"
    assert decision["requires_decision"] is True
