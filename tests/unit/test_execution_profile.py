from asteria_runtime.core.execution_profile import (
    HARNESS,
    SESSION_AGENT,
    execution_profile_from_run_config,
    resolve_execution_profile,
    session_agent_recommended_command,
)
from asteria_runtime.core.fast_path_policy import classify_fast_path


def test_resolve_execution_profile_defaults_to_session_agent() -> None:
    resolution = resolve_execution_profile("给 CLI 增加 --version 并补 pytest。")
    assert resolution.profile_id == SESSION_AGENT
    assert resolution.collapse_to_single_task is True
    assert resolution.use_replan_lineage is False


def test_resolve_execution_profile_high_risk_uses_harness() -> None:
    resolution = resolve_execution_profile("Deploy to production and push secrets.")
    assert resolution.profile_id == HARNESS
    assert resolution.use_replan_lineage is True


def test_resolve_execution_profile_parallel_writes_uses_harness() -> None:
    resolution = resolve_execution_profile("Update README", parallel_writes=True)
    assert resolution.profile_id == HARNESS


def test_session_agent_recommended_command_maps_replan_to_resume() -> None:
    assert session_agent_recommended_command("replan", is_session_agent=True) == "resume"
    assert session_agent_recommended_command("replan", is_session_agent=False) == "replan"
    assert session_agent_recommended_command("debug", is_session_agent=True) == "debug"


def test_execution_profile_from_run_config_round_trip() -> None:
    fp = classify_fast_path("update docs/README.md")
    resolution = resolve_execution_profile("update docs/README.md", fast_path=fp)
    loaded = execution_profile_from_run_config(
        {"execution_profile": resolution.to_dict(), "fast_path": fp.to_dict()}
    )
    assert loaded.profile_id == SESSION_AGENT
    assert loaded.loop_profile_id == "session_agent"
