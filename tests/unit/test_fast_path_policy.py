from asteria_runtime.core.fast_path_policy import classify_fast_path, classify_risk_tier


def test_classify_risk_tier_high_from_deploy_signal() -> None:
    risk = classify_risk_tier("Fix auth permissions and deploy to production.")
    assert risk.risk_tier == "high"


def test_classify_risk_tier_readonly_from_task_contract() -> None:
    risk = classify_risk_tier(
        "Research codebase structure",
        task={"parallel_safety": "readonly", "write_scope": []},
    )
    assert risk.risk_tier == "readonly"


def test_classify_risk_tier_explicit_on_goal_spec() -> None:
    risk = classify_risk_tier("anything", goal_spec={"risk_tier": "default"})
    assert risk.risk_tier == "default"


def test_fast_path_policy_classifies_doc_update_from_artifact_scope() -> None:
    policy = classify_fast_path(
        "Update local setup guide.",
        target_files=["docs/README.md"],
    )

    assert policy.risk_tier == "default"
    assert policy.task_kind == "doc_update"
    assert policy.review_tier == "deterministic"
    assert policy.context_mode == "slim"


def test_fast_path_policy_classifies_single_file_bugfix_from_task_contract() -> None:
    policy = classify_fast_path(
        "Fix parser behavior.",
        target_files=["src/parser.py"],
        task={
            "task_kind": "diagnostic",
            "write_scope": ["src/parser.py"],
            "expected_artifacts": ["src/parser.py"],
        },
    )

    assert policy.task_kind == "single_file_bugfix"
    assert policy.review_tier == "deterministic_then_medium"
    assert policy.deterministic_first is True


def test_fast_path_policy_allows_test_file_as_bugfix_context() -> None:
    policy = classify_fast_path(
        "Fix calc module behavior.",
        target_files=["calc.py"],
        task={
            "task_kind": "diagnostic",
            "write_scope": ["calc.py"],
            "expected_artifacts": ["calc.py", "test_calc.py"],
        },
    )

    assert policy.task_kind == "single_file_bugfix"
    assert policy.context_mode == "slim"


def test_fast_path_policy_simple_file_from_single_scoped_artifact() -> None:
    policy = classify_fast_path(
        "Create output artifact.",
        target_files=["result.json"],
        task={"write_scope": ["result.json"], "expected_artifacts": ["result.json"]},
    )

    assert policy.task_kind == "simple_file"
    assert policy.context_mode == "slim"


def test_fast_path_policy_keeps_high_risk_on_strong_route() -> None:
    policy = classify_fast_path("Fix auth permissions and deploy to production.")

    assert policy.task_kind == "high_risk"
    assert policy.risk_tier == "high"
    assert policy.goal_spec_tier == "strong"
    assert policy.review_tier == "strong"
    assert policy.strong_allowed is True
