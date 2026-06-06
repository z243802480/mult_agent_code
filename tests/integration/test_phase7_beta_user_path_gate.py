from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.studio_command import StudioCommand, resolve_studio_dir


GATE = json.loads(Path("benchmarks/phase7_beta_user_path_gate.json").read_text(encoding="utf-8"))


def test_phase7_beta_user_path_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "7"
    assert Path(GATE["onboarding_doc"]).exists()
    assert Path(GATE["beta_tasks_manifest"]).exists()
    assert Path(GATE["signoff_report"]).parent.exists()
    assert "tests/integration/test_phase7_beta_user_path_gate.py" in GATE["contract_tests"]


def test_beta_user_tasks_manifest_has_three_tasks() -> None:
    manifest = json.loads(Path(GATE["beta_tasks_manifest"]).read_text(encoding="utf-8"))
    tasks = manifest.get("tasks") or []
    assert len(tasks) >= 3
    assert manifest.get("minimum_ready_score", 0) >= 0.8


def test_beta_onboarding_doc_links_tasks_and_studio() -> None:
    doc = Path(GATE["onboarding_doc"]).read_text(encoding="utf-8")
    assert "asteria studio" in doc
    assert "beta_user_tasks.json" in doc
    assert "审查" in doc or "review" in doc.lower()
    assert "accept" in doc.lower() or "接受" in doc
    assert "accept --latest" not in doc
    assert "asteria accept --root" in doc


def test_beta_gate_required_commands_match_cli() -> None:
    for command in GATE["required_commands"]:
        assert "--latest" not in command


def test_studio_command_resolves_repo_studio_dir() -> None:
    studio_dir = resolve_studio_dir()
    assert studio_dir.is_dir()
    assert (studio_dir / "server.mjs").is_file()


def test_beta_b6_restricted_sim_artifacts_exist() -> None:
    assert Path(GATE["b6_restricted_sim_script"]).exists()
    assert Path(GATE["b6_restricted_sim_report"]).exists()
    assert Path(GATE["b6_trial_checklist"]).exists()
    assert Path(GATE["b6_maintainer_template"]).exists()
    criteria = GATE.get("b6_pass_criteria") or {}
    assert criteria.get("task_id") == "small_code_change"
    assert criteria.get("tester_is_non_maintainer") is True


def test_beta_trial_checklist_is_tester_facing() -> None:
    checklist = Path(GATE["b6_trial_checklist"]).read_text(encoding="utf-8")
    assert "30 分钟" in checklist
    assert "gate" not in checklist.lower() or "不要" in checklist
    assert "审查结果" in checklist or "review" in checklist.lower()


def test_studio_command_launch_config() -> None:
    command = StudioCommand(Path("."), skip_install=True, open_browser=False)
    assert command.studio_dir.name == "studio"
    assert command.api_port == 8787
    assert command.ui_port == 5174
