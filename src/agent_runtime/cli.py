from __future__ import annotations

import argparse
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.plan_command import PlanCommand


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="Agent runtime CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser("init", help="Initialize an agent-ready workspace")
    init_parser.add_argument("--root", default=".", help="Workspace root path")
    init_parser.add_argument(
        "--profile",
        choices=["auto", "planning", "codebase", "empty"],
        default="auto",
        help="Workspace profile hint",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate managed metadata; never overwrites user-authored AGENTS.md",
    )

    plan_parser = subcommands.add_parser("plan", help="Generate GoalSpec and task plan")
    plan_parser.add_argument("goal", help="Natural-language goal")
    plan_parser.add_argument("--root", default=".", help="Workspace root path")

    compact_parser = subcommands.add_parser("compact", help="Create a context snapshot")
    compact_parser.add_argument("--root", default=".", help="Workspace root path")
    compact_parser.add_argument("--run-id", default=None, help="Run id to compact; defaults to latest run")
    compact_parser.add_argument("--focus", default="manual context compaction", help="Snapshot focus")

    execute_parser = subcommands.add_parser("execute", help="Execute ready tasks from a planned run")
    execute_parser.add_argument("--root", default=".", help="Workspace root path")
    execute_parser.add_argument("--run-id", default=None, help="Run id to execute; defaults to latest run")
    execute_parser.add_argument("--max-tasks", type=int, default=1, help="Maximum ready tasks to execute")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        result = InitCommand(root=Path(args.root), profile=args.profile, force=args.force).run()
        print(result.to_text())
        return

    if args.command == "plan":
        result = PlanCommand(root=Path(args.root), goal=args.goal).run()
        print(result.to_text())
        return

    if args.command == "compact":
        result = CompactCommand(root=Path(args.root), run_id=args.run_id, focus=args.focus).run()
        print(result.to_text())
        return

    if args.command == "execute":
        result = ExecuteCommand(root=Path(args.root), run_id=args.run_id, max_tasks=args.max_tasks).run()
        print(result.to_text())
        return

    parser.error(f"Unsupported command: {args.command}")
