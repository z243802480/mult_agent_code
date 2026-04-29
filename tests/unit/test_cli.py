from __future__ import annotations

from agent_runtime.cli import build_parser


def test_slash_command_aliases_parse_like_regular_commands() -> None:
    parser = build_parser()

    plan_args = parser.parse_args(["/plan", "build a tool", "--root", "."])
    new_args = parser.parse_args(["/new", "build a tool", "--root", "."])
    sessions_args = parser.parse_args(["/sessions", "--root", ".", "--limit", "3"])
    runs_args = parser.parse_args(["/runs", "--root", ".", "--run-id", "run-1"])
    execute_args = parser.parse_args(["/execute", "--root", ".", "--session-id", "run-1"])
    brainstorm_args = parser.parse_args(["/brainstorm", "build a tool", "--root", ".", "--apply"])
    acceptance_args = parser.parse_args(
        ["/acceptance", "--root", ".", "--suite", "offline", "--allow-fake"]
    )

    assert plan_args.command == "/plan"
    assert plan_args.goal == "build a tool"
    assert new_args.command == "/new"
    assert new_args.goal == "build a tool"
    assert sessions_args.command == "/sessions"
    assert sessions_args.limit == 3
    assert runs_args.command == "/runs"
    assert runs_args.session_id == "run-1"
    assert execute_args.session_id == "run-1"
    assert brainstorm_args.command == "/brainstorm"
    assert brainstorm_args.goal == "build a tool"
    assert brainstorm_args.apply
    assert acceptance_args.command == "/acceptance"
    assert acceptance_args.suite == "offline"
    assert acceptance_args.allow_fake
