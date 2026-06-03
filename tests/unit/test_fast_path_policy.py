from asteria_runtime.core.fast_path_policy import classify_fast_path


def test_fast_path_policy_classifies_doc_update_as_medium_deterministic() -> None:
    policy = classify_fast_path("Update README documentation for local setup.")

    assert policy.task_kind == "doc_update"
    assert policy.goal_spec_tier == "medium"
    assert policy.review_tier == "deterministic"
    assert policy.context_mode == "slim"
    assert policy.strong_allowed is False


def test_fast_path_policy_classifies_single_file_bugfix_without_strong_default() -> None:
    policy = classify_fast_path(
        "Fix the failing pytest for parser.py.",
        target_files=["src/parser.py"],
    )

    assert policy.task_kind == "single_file_bugfix"
    assert policy.goal_spec_tier == "medium"
    assert policy.review_tier == "deterministic_then_medium"
    assert policy.deterministic_first is True


def test_fast_path_policy_allows_test_file_as_bugfix_verification_context() -> None:
    policy = classify_fast_path(
        "Fix calc.py so add(2, 3) returns 5 and keep the existing test intent.",
        target_files=["calc.py", "test_calc.py"],
    )

    assert policy.task_kind == "single_file_bugfix"
    assert policy.context_mode == "slim"
    assert policy.strong_allowed is False


def test_fast_path_policy_keeps_high_risk_on_strong_route() -> None:
    policy = classify_fast_path("Fix auth permissions and deploy to production.")

    assert policy.task_kind == "high_risk"
    assert policy.risk == "high"
    assert policy.goal_spec_tier == "strong"
    assert policy.review_tier == "strong"
    assert policy.strong_allowed is True
