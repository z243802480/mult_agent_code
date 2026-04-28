from __future__ import annotations

import argparse
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.model_check_command import ModelCheckCommand
from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.commands.review_command import ReviewCommand
from agent_runtime.commands.run_command import RunCommand
from agent_runtime.commands.resume_command import ResumeCommand


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

    model_parser = subcommands.add_parser("model-check", help="Validate model provider configuration")
    model_parser.add_argument("--root", default=".", help="Workspace root path")
    model_parser.add_argument("--skip-call", action="store_true", help="Only validate local configuration")

    plan_parser = subcommands.add_parser("plan", help="Generate GoalSpec and task plan")
    plan_parser.add_argument("goal", help="Natural-language goal")
    plan_parser.add_argument("--root", default=".", help="Workspace root path")

    research_parser = subcommands.add_parser("research", help="Collect sources and synthesize research")
    research_parser.add_argument("query", help="Research question")
    research_parser.add_argument("--root", default=".", help="Workspace root path")
    research_parser.add_argument("--run-id", default=None, help="Run id; creates a research run if omitted")
    research_parser.add_argument("--url", action="append", default=[], help="URL to include as a source")
    research_parser.add_argument("--no-local", action="store_true", help="Disable local document search")
    research_parser.add_argument("--serper", action="store_true", help="Use Serper search when configured")
    research_parser.add_argument("--max-sources", type=int, default=12, help="Maximum sources to collect")

    run_parser = subcommands.add_parser("run", help="Plan, execute, repair, review, and report")
    run_parser.add_argument("goal", help="Natural-language goal")
    run_parser.add_argument("--root", default=".", help="Workspace root path")
    run_parser.add_argument("--max-iterations", type=int, default=None, help="Maximum run loop iterations")
    run_parser.add_argument("--max-tasks-per-iteration", type=int, default=1, help="Tasks to execute per iteration")

    resume_parser = subcommands.add_parser("resume", help="Resume a paused run after decisions")
    resume_parser.add_argument("--root", default=".", help="Workspace root path")
    resume_parser.add_argument("--run-id", default=None, help="Run id; defaults to latest run")
    resume_parser.add_argument("--max-iterations", type=int, default=None, help="Maximum run loop iterations")
    resume_parser.add_argument(
        "--max-tasks-per-iteration",
        type=int,
        default=1,
        help="Tasks to execute per iteration",
    )

    compact_parser = subcommands.add_parser("compact", help="Create a context snapshot")
    compact_parser.add_argument("--root", default=".", help="Workspace root path")
    compact_parser.add_argument("--run-id", default=None, help="Run id to compact; defaults to latest run")
    compact_parser.add_argument("--focus", default="manual context compaction", help="Snapshot focus")

    execute_parser = subcommands.add_parser("execute", help="Execute ready tasks from a planned run")
    execute_parser.add_argument("--root", default=".", help="Workspace root path")
    execute_parser.add_argument("--run-id", default=None, help="Run id to execute; defaults to latest run")
    execute_parser.add_argument("--max-tasks", type=int, default=1, help="Maximum ready tasks to execute")

    debug_parser = subcommands.add_parser("debug", help="Repair blocked tasks from a run")
    debug_parser.add_argument("--root", default=".", help="Workspace root path")
    debug_parser.add_argument("--run-id", default=None, help="Run id to debug; defaults to latest run")
    debug_parser.add_argument("--task-id", default=None, help="Specific blocked task to repair")
    debug_parser.add_argument("--max-repairs", type=int, default=1, help="Maximum blocked tasks to repair")

    review_parser = subcommands.add_parser("review", help="Evaluate a run and write review reports")
    review_parser.add_argument("--root", default=".", help="Workspace root path")
    review_parser.add_argument("--run-id", default=None, help="Run id to review; defaults to latest run")

    decide_parser = subcommands.add_parser("decide", help="Create, list, or resolve user decision points")
    decide_parser.add_argument("--root", default=".", help="Workspace root path")
    decide_parser.add_argument("--run-id", default=None, help="Run id; defaults to latest run")
    decide_parser.add_argument("--question", default=None, help="Decision question for creation")
    decide_parser.add_argument("--options-json", default=None, help="JSON array of options")
    decide_parser.add_argument("--recommended-option-id", default=None, help="Recommended option id")
    decide_parser.add_argument("--default-option-id", default=None, help="Default option id")
    decide_parser.add_argument("--impact-json", default=None, help="JSON impact object")
    decide_parser.add_argument("--decision-id", default=None, help="Decision id to create or resolve")
    decide_parser.add_argument("--select-option-id", default=None, help="Resolve with this option id")
    decide_parser.add_argument("--use-default", action="store_true", help="Resolve with default option")
    decide_parser.add_argument("--list-pending", action="store_true", help="List pending decisions")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        init_result = InitCommand(root=Path(args.root), profile=args.profile, force=args.force).run()
        print(init_result.to_text())
        return

    if args.command == "model-check":
        model_result = ModelCheckCommand(root=Path(args.root), skip_call=args.skip_call).run()
        print(model_result.to_text())
        return

    if args.command == "plan":
        plan_result = PlanCommand(root=Path(args.root), goal=args.goal).run()
        print(plan_result.to_text())
        return

    if args.command == "research":
        research_result = ResearchCommand(
            root=Path(args.root),
            query=args.query,
            run_id=args.run_id,
            urls=args.url,
            use_local=not args.no_local,
            use_serper=args.serper,
            max_sources=args.max_sources,
        ).run()
        print(research_result.to_text())
        return

    if args.command == "run":
        run_result = RunCommand(
            root=Path(args.root),
            goal=args.goal,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
        ).run()
        print(run_result.to_text())
        return

    if args.command == "resume":
        resume_result = ResumeCommand(
            root=Path(args.root),
            run_id=args.run_id,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
        ).run()
        print(resume_result.to_text())
        return

    if args.command == "compact":
        compact_result = CompactCommand(root=Path(args.root), run_id=args.run_id, focus=args.focus).run()
        print(compact_result.to_text())
        return

    if args.command == "execute":
        execute_result = ExecuteCommand(root=Path(args.root), run_id=args.run_id, max_tasks=args.max_tasks).run()
        print(execute_result.to_text())
        return

    if args.command == "debug":
        debug_result = DebugCommand(
            root=Path(args.root),
            run_id=args.run_id,
            task_id=args.task_id,
            max_repairs=args.max_repairs,
        ).run()
        print(debug_result.to_text())
        return

    if args.command == "review":
        review_result = ReviewCommand(root=Path(args.root), run_id=args.run_id).run()
        print(review_result.to_text())
        return

    if args.command == "decide":
        decide_result = DecideCommand(
            root=Path(args.root),
            run_id=args.run_id,
            question=args.question,
            options_json=args.options_json,
            recommended_option_id=args.recommended_option_id,
            default_option_id=args.default_option_id,
            impact_json=args.impact_json,
            decision_id=args.decision_id,
            select_option_id=args.select_option_id,
            use_default=args.use_default,
            list_pending=args.list_pending,
        ).run()
        print(decide_result.to_text())
        return

    parser.error(f"Unsupported command: {args.command}")
