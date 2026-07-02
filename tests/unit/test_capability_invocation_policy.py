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
    # write/execute keep the real interactive "ask" gate; MCP is contract-gated, not an
    # interactive prompt, so it reports the honest "allow" (no gate the runtime never honours).
    assert policy["mcp_permission"] == "allow"


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


def test_capability_invocation_policy_permits_goal_skills_by_mode_not_artifact_only() -> None:
    # Skills are now gated by the task's allowed_skills contract + permission mode (mirroring MCP),
    # not restricted to the _ARTIFACT_SKILLS map. At the policy level a goal may load any skill by
    # mode/risk; the per-skill restriction is the allowed_skills contract (see the
    # capability_decision_recorder tests). This makes user-shipped SKILL.md skills usable.
    policy = CapabilityInvocationPolicy()

    def skill(name: str, *, task_kind: str = "implementation", intent: str = "implementation_goal", risk: str = "medium"):
        return policy.for_tool(
            name,
            intent=intent,
            task_kind=task_kind,
            permission_mode="reviewed_auto",
            risk=risk,
            capability_type="skill",
        )

    # an artifact skill and an arbitrary user skill are both policy-permitted for a goal
    assert skill("documents", task_kind="document", intent="document_goal")["decision"] == "allow"
    assert skill("spreadsheets", task_kind="document", intent="document_goal")["decision"] == "allow"
    assert skill("greet")["decision"] == "allow"
    # Skills are gated by the allowed_skills contract, not an interactive prompt: a high-risk
    # skill is allowed within contract (no fake "ask" the runtime never honours).
    assert skill("greet", risk="high")["decision"] == "allow"
    # chat / brainstorm still deny skills entirely (no "doing" capability on lightweight intents)
    assert skill("greet", task_kind="chat", intent="ordinary_chat", risk="low")["decision"] == "deny"
    assert skill("greet", task_kind="brainstorm", intent="brainstorm_goal", risk="low")["decision"] == "deny"


def test_capability_invocation_policy_mcp_allowed_within_contract_not_fake_ask() -> None:
    # MCP is gated by the allowed_mcp contract, not an interactive prompt. Even at high risk the
    # policy returns an honest "allow" (the risk tier is still recorded) instead of a "requires
    # decision" that nothing in the runtime ever honours.
    decision = CapabilityInvocationPolicy().for_tool(
        "mcp",
        intent="research_goal",
        task_kind="research",
        permission_mode="auto",
        risk="high",
        capability_type="mcp",
    )

    assert decision["decision"] == "allow"
    assert decision["requires_decision"] is False
    assert decision["risk"] == "high"
