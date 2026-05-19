from asteria_runtime.core.deadline_budget import DeadlineBudget, apply_deadline_budget_env


def test_deadline_budget_derives_phase_budgets_from_scenario_budget() -> None:
    budget = DeadlineBudget.for_scenario(
        600,
        model_max_retries=1,
        suite_seconds=1260,
    )

    assert budget.as_dict() == {
        "suite_seconds": 1260,
        "scenario_seconds": 600,
        "subprocess_seconds": 600,
        "run_seconds": 570,
        "smoke_command_seconds": 570,
        "review_seconds": 90,
        "recovery_seconds": 200,
        "provider_call_seconds": 90,
        "cheap_provider_call_seconds": 45,
        "stream_idle_timeout_seconds": 30,
        "model_max_retries": 1,
    }


def test_deadline_budget_env_sets_provider_and_review_limits() -> None:
    env: dict[str, str] = {}
    apply_deadline_budget_env(env, DeadlineBudget.for_scenario(240, model_max_retries=1))

    assert env["AGENT_MODEL_STRONG_TIMEOUT_SECONDS"] == "60"
    assert env["AGENT_MODEL_MEDIUM_TIMEOUT_SECONDS"] == "60"
    assert env["AGENT_MODEL_CHEAP_TIMEOUT_SECONDS"] == "45"
    assert env["AGENT_MODEL_STRONG_MAX_RETRIES"] == "1"
    assert env["AGENT_MODEL_SMOKE_COMMAND_TIMEOUT_SECONDS"] == "210"
    assert env["AGENT_MODEL_SMOKE_REVIEW_TIMEOUT_SECONDS"] == "40"
    assert env["AGENT_MODEL_SMOKE_RECOVERY_TIMEOUT_SECONDS"] == "80"
    assert env["AGENT_MODEL_STRONG_STREAM_IDLE_TIMEOUT_SECONDS"] == "30"
