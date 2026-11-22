"""Explicit controller binding for legacy synthetic test reports; no model proof implied."""

from asteria_runtime.core.review_artifacts import collect_review_artifacts
from asteria_runtime.core.review_freshness import capture_review_binding
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.json_store import JsonStore


def bind_fixture_review(root, run_dir, validator):
    from asteria_runtime.commands.init_command import InitCommand

    if not (root / ".asteria/policies.json").exists():
        InitCommand(root).run()
    store = JsonStore(validator)
    goal = store.read(run_dir / "goal_spec.json", "goal_spec")
    board = store.read(run_dir / "task_plan.json", "task_board")
    policy = load_policy_config(root / ".asteria", validator)
    artifacts = collect_review_artifacts(
        RuntimeContext(root, run_dir.name, policy, validator), goal, board
    )
    store.write(run_dir / (artifacts["evidence_id"] + ".json"), artifacts, "review_artifacts")
    report = store.read(run_dir / "eval_report.json", "eval_report")
    report["artifact_eval"]["current_artifacts_evidence"] = {
        "evidence_id": artifacts["evidence_id"],
        "complete": artifacts["complete"],
    }
    binding = capture_review_binding(
        root, run_dir, artifacts, policy.get("protected_paths", []), goal=goal, board=board
    )
    validator.validate("review_binding", binding)
    report["artifact_eval"]["review_binding"] = binding
    store.write(run_dir / "eval_report.json", report, "eval_report")
    return report
