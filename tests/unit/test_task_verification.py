from types import SimpleNamespace

from asteria_runtime.core.task_verification import (
    commands_needing_execution, declared_commands, declared_observations,
)


def task():
    return {"validation_commands": ["check core"],
            "verification_policy": {"command_source": "planner_task"}}


def obs(command, ok=True, name="run_tests"):
    return SimpleNamespace(tool_name=name, ok=ok, data={"command": command})


def test_declared_checks_exclude_probes_but_keep_required_failures():
    required = obs("check core", False)
    observations = [required, obs("exploratory full suite", False), obs("different green check")]
    assert declared_observations(task(), observations) == [required]
    assert commands_needing_execution(task(), observations) == ["check core"]


def test_fresh_required_evidence_is_reused_and_rerun_after_a_write():
    observations = [obs("check core"), obs("", name="read_file")]
    assert commands_needing_execution(task(), observations) == []
    observations.append(obs("", name="write_file"))
    assert commands_needing_execution(task(), observations) == ["check core"]


def test_an_unchanged_required_failure_is_not_needlessly_retried():
    assert commands_needing_execution(task(), [obs("check core", False)]) == []


def test_missing_check_is_failure_and_legacy_has_no_opt_in():
    missing = declared_observations(task(), [obs("other green")])
    assert len(missing) == 1 and not missing[0].ok
    assert missing[0].data["command"] == "check core"
    assert declared_commands({"validation_commands": ["legacy"]}) == []
