from __future__ import annotations

from agent_runtime.cli import build_parser


def test_slash_command_aliases_parse_like_regular_commands() -> None:
    parser = build_parser()

    plan_args = parser.parse_args(["/plan", "build a tool", "--root", "."])
    new_args = parser.parse_args(["/new", "build a tool", "--root", "."])
    sessions_args = parser.parse_args(["/sessions", "--root", ".", "--limit", "3", "--context"])
    verification_args = parser.parse_args(["/verification", "--root", "."])
    runs_args = parser.parse_args(["/runs", "--root", ".", "--run-id", "run-1"])
    execute_args = parser.parse_args(["/execute", "--root", ".", "--session-id", "run-1"])
    replan_args = parser.parse_args(
        ["/replan", "--root", ".", "--session-id", "run-1", "--max-items", "3"]
    )
    brainstorm_args = parser.parse_args(["/brainstorm", "build a tool", "--root", ".", "--apply"])
    acceptance_args = parser.parse_args(
        [
            "/acceptance",
            "--root",
            ".",
            "--suite",
            "nightly",
            "--allow-fake",
            "--fail-on-trend-warning",
            "--warn-model-call-delta",
            "8",
        ]
    )
    acceptance_history_args = parser.parse_args(
        [
            "/acceptance-history",
            "--root",
            ".",
            "--suite",
            "smoke",
            "--limit",
            "2",
            "--warn-model-call-delta",
            "7",
            "--warn-duration-delta",
            "30",
            "--fail-on-warning",
        ]
    )

    assert plan_args.command == "/plan"
    assert plan_args.goal == "build a tool"
    assert new_args.command == "/new"
    assert new_args.goal == "build a tool"
    assert sessions_args.command == "/sessions"
    assert sessions_args.limit == 3
    assert sessions_args.context
    assert verification_args.command == "/verification"
    assert runs_args.command == "/runs"
    assert runs_args.session_id == "run-1"
    assert execute_args.session_id == "run-1"
    assert replan_args.command == "/replan"
    assert replan_args.max_items == 3
    assert brainstorm_args.command == "/brainstorm"
    assert brainstorm_args.goal == "build a tool"
    assert brainstorm_args.apply
    assert acceptance_args.command == "/acceptance"
    assert acceptance_args.suite == "nightly"
    assert acceptance_args.allow_fake
    assert acceptance_args.fail_on_trend_warning
    assert acceptance_args.warn_model_call_delta == 8
    assert acceptance_history_args.command == "/acceptance-history"
    assert acceptance_history_args.suite == "smoke"
    assert acceptance_history_args.limit == 2
    assert acceptance_history_args.warn_model_call_delta == 7
    assert acceptance_history_args.warn_duration_delta == 30
    assert acceptance_history_args.fail_on_warning

    promote_args = parser.parse_args(["/acceptance", "--root", ".", "--promote-failures"])
    assert promote_args.promote_failures

    run_promoted_args = parser.parse_args(
        [
            "/acceptance",
            "--root",
            ".",
            "--promote-failures",
            "--run-promoted",
            "--rerun-promoted",
            "--promoted-run-max-iterations",
            "2",
            "--promoted-run-max-tasks-per-iteration",
            "3",
        ]
    )
    assert run_promoted_args.run_promoted
    assert run_promoted_args.rerun_promoted
    assert run_promoted_args.promoted_run_max_iterations == 2
    assert run_promoted_args.promoted_run_max_tasks_per_iteration == 3
