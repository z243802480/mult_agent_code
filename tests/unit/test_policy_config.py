import json
from pathlib import Path

from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_load_policy_config_migrates_missing_default_keys(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".asteria"
    agent_dir.mkdir()
    policy_path = agent_dir / "policies.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "decision_granularity": "balanced",
                "budgets": {
                    "max_model_calls_per_goal": 60,
                    "max_tool_calls_per_goal": 120,
                    "max_total_minutes_per_goal": 30,
                    "max_iterations_per_goal": 8,
                    "max_repair_attempts_total": 5,
                    "max_repair_attempts_per_task": 2,
                    "max_research_calls": 5,
                    "max_user_decisions": 5,
                },
                "context": {
                    "compaction_threshold": 0.75,
                    "hard_stop_threshold": 0.9,
                    "phase_boundary_compaction": True,
                    "handoff_compaction": True,
                },
                "permissions": {
                    "allow_network": False,
                    "allow_shell": True,
                    "allow_destructive_shell": False,
                    "allow_global_package_install": False,
                    "allow_secret_file_read": False,
                    "allow_remote_push": False,
                    "allow_deploy": False,
                },
                "protected_paths": [".env", "secrets/"],
                "model_routing": {},
                "commands": {},
            }
        ),
        encoding="utf-8",
    )

    policy = load_policy_config(agent_dir, SchemaValidator(Path.cwd() / "schemas"))

    assert policy["permissions"]["allow_restore_delete_created_files"] is True
    assert policy["budgets"]["max_replans_per_task"] == 2
    persisted = json.loads(policy_path.read_text(encoding="utf-8"))
    assert persisted["permissions"]["allow_restore_delete_created_files"] is True
