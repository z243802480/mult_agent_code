from __future__ import annotations

from agent_runtime.cli import build_parser


def test_slash_command_aliases_parse_like_regular_commands() -> None:
    parser = build_parser()

    plan_args = parser.parse_args(["/plan", "build a tool", "--root", "."])
    new_args = parser.parse_args(["/new", "build a tool", "--root", "."])
    runs_args = parser.parse_args(["/runs", "--root", ".", "--limit", "3"])

    assert plan_args.command == "/plan"
    assert plan_args.goal == "build a tool"
    assert new_args.command == "/new"
    assert new_args.goal == "build a tool"
    assert runs_args.command == "/runs"
    assert runs_args.limit == 3
