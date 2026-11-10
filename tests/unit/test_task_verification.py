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


def readonly_task(paths):
    return {"task_kind": "diagnostic", "write_scope": [], "validation_commands": [],
            "verification_policy": {"command_source": "planner_task", "readback_paths": paths}}


def test_readback_contract_selects_each_required_path_not_exploratory_errors():
    required = obs("", name="read_file")
    required.data = {"path": "src/module.py"}
    probe = obs("exploratory timeout", False)
    assert declared_observations(readonly_task(["src/module.py"]), [probe, required]) == [required]
    assert not probe.ok


def test_required_readback_missing_and_latest_failure_are_not_masked():
    good = obs("", name="read_file")
    good.data = {"path": "README.md"}
    bad = obs("", False, name="read_file")
    bad.data = {"path": "README.md", "error_type": "PermissionError"}
    assert declared_observations(readonly_task(["README.md"]), [good, bad]) == [bad]
    missing = declared_observations(readonly_task(["absent.md"]), [good])
    assert len(missing) == 1 and not missing[0].ok
    assert missing[0].data["path"] == "absent.md"


def test_readback_contract_does_not_opt_implementation_into_readonly_acceptance():
    current = readonly_task(["README.md"])
    current["task_kind"] = "implementation"
    assert declared_observations(current, []) == []


def test_stale_readback_and_command_cannot_pass_when_budget_prevents_recheck(tmp_path):
    from asteria_runtime.core.task_verification import has_declared_checks, readbacks_needing_execution
    good = obs("", name="read_file")
    good.data = {"path": "README.md"}
    mutation = obs("arbitrary command")
    current = readonly_task(["README.md"])
    assert readbacks_needing_execution(current, [good, mutation]) == ["README.md"]
    assert not declared_observations(current, [good, mutation])[0].ok
    assert not declared_observations(task(), [obs("check core"), mutation])[0].ok
    assert has_declared_checks(readonly_task([]))
    assert declared_observations(readonly_task([]), [good]) == []
    bad = obs("", False, name="read_file")
    bad.data = {"path": str(tmp_path / "README.md")}
    assert declared_observations(current, [good, bad], tmp_path) == [bad]
