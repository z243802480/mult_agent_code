from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.run_config import build_run_config, effective_policy_for_run
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _workspace_files_outside_runtime(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or ".asteria" in relative.parts:
            continue
        files[relative.as_posix()] = path.read_text(encoding="utf-8")
    return files


def test_run_config_maps_user_modes_to_effective_policy(tmp_path: Path) -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    config = build_run_config(
        run_id="run-0001",
        mode="goal",
        permission_level="ask",
        model_strategy="quality",
    )

    validator.validate("run_config", config)
    assert config["decision_granularity"] == "manual"
    assert config["permission_overrides"]["allow_remote_push"] is False
    assert config["model_routing_overrides"] == {}
    assert config["model_strategy_profile"]["strategy"] == "quality"
    assert config["model_strategy_profile"]["selection_policy"] == (
        "prefer_capability_fit_with_budget"
    )


def test_plan_persists_run_config_and_effective_policy_overrides(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    result = PlanCommand(
        tmp_path,
        "Create a tiny offline artifact",
        model_client=FakeModelClient(),
        mode="goal",
        permission_level="ask",
        model_strategy="economy",
    ).run()
    validator = SchemaValidator(SCHEMA_DIR)
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    config = JsonStore(validator).read(run_dir / "run_config.json", "run_config")

    assert config["mode"] == "goal"
    assert config["permission_level"] == "ask"
    assert config["model_strategy"] == "economy"
    assert config["decision_granularity"] == "manual"

    base_policy = JsonStore(validator).read(
        tmp_path / ".asteria" / "policies.json", "policy_config"
    )
    effective = effective_policy_for_run(policy=base_policy, run_dir=run_dir, validator=validator)
    assert effective["decision_granularity"] == "manual"
    assert effective["model_routing"] == base_policy["model_routing"]
    assert effective["model_strategy_profile"]["strategy"] == "economy"
    assert effective["model_strategy_profile"]["selection_policy"] == (
        "prefer_low_cost_with_safety_escalation"
    )
    assert effective["permissions"]["allow_remote_push"] is False


def test_plan_mode_does_not_modify_workspace_files_outside_runtime(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    (tmp_path / "README.md").write_text("# Existing project\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('keep me')\n", encoding="utf-8")
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "context.txt").write_text("user-authored notes\n", encoding="utf-8")
    before = _workspace_files_outside_runtime(tmp_path)

    result = PlanCommand(
        tmp_path,
        "Create a tiny offline artifact",
        model_client=FakeModelClient(),
        mode="plan",
        permission_level="ask",
        model_strategy="auto",
    ).run()

    after = _workspace_files_outside_runtime(tmp_path)
    assert after == before

    runtime_root = tmp_path / ".asteria"
    for artifact_path in (
        result.goal_spec_path,
        result.task_plan_path,
        result.task_plan_eval_path,
        result.cost_report_path,
    ):
        artifact_path.relative_to(runtime_root)
        assert artifact_path.exists()
    assert (runtime_root / "tasks" / "backlog.json").exists()
