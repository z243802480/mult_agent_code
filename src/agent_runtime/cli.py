from __future__ import annotations

import argparse
from pathlib import Path

from agent_runtime.commands.acceptance_command import AcceptanceCommand
from agent_runtime.commands.brainstorm_command import BrainstormCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.model_check_command import ModelCheckCommand
from agent_runtime.commands.new_command import NewCommand
from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.handoff_command import HandoffCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.commands.review_command import ReviewCommand
from agent_runtime.commands.run_command import RunCommand
from agent_runtime.commands.resume_command import ResumeCommand
from agent_runtime.commands.sessions_command import SessionsCommand


def add_session_id_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "--session-id",
        "--run-id",
        dest="session_id",
        default=None,
        help=help_text,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="Agent runtime CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser(
        "init",
        aliases=["/init"],
        help="Initialize an agent-ready workspace",
    )
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

    model_parser = subcommands.add_parser(
        "model-check",
        aliases=["/model-check"],
        help="Validate model provider configuration",
    )
    model_parser.add_argument("--root", default=".", help="Workspace root path")
    model_parser.add_argument(
        "--skip-call",
        action="store_true",
        help="Only validate local configuration",
    )

    plan_parser = subcommands.add_parser(
        "plan",
        aliases=["/plan"],
        help="Generate GoalSpec and task plan",
    )
    plan_parser.add_argument("goal", help="Natural-language goal")
    plan_parser.add_argument("--root", default=".", help="Workspace root path")

    new_parser = subcommands.add_parser(
        "new",
        aliases=["/new"],
        help="Start a new isolated goal context",
    )
    new_parser.add_argument("goal", help="Natural-language goal")
    new_parser.add_argument("--root", default=".", help="Workspace root path")

    sessions_parser = subcommands.add_parser(
        "sessions",
        aliases=["/sessions", "runs", "/runs", "history", "/history"],
        help="List, show, or select session contexts",
    )
    sessions_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(sessions_parser, "Session id to show or select")
    sessions_parser.add_argument(
        "--set-current",
        action="store_true",
        help="Set session as current",
    )
    sessions_parser.add_argument("--limit", type=int, default=20, help="Maximum sessions to list")

    research_parser = subcommands.add_parser(
        "research",
        aliases=["/research"],
        help="Collect sources and synthesize research",
    )
    research_parser.add_argument("query", help="Research question")
    research_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(research_parser, "Session id; creates a research session if omitted")
    research_parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="URL to include as a source",
    )
    research_parser.add_argument(
        "--no-local",
        action="store_true",
        help="Disable local document search",
    )
    research_parser.add_argument(
        "--serper",
        action="store_true",
        help="Use Serper search when configured",
    )
    research_parser.add_argument(
        "--max-sources",
        type=int,
        default=12,
        help="Maximum sources to collect",
    )

    brainstorm_parser = subcommands.add_parser(
        "brainstorm",
        aliases=["/brainstorm"],
        help="Generate and score product or implementation directions",
    )
    brainstorm_parser.add_argument(
        "goal", nargs="?", help="Goal to brainstorm; defaults to current session"
    )
    brainstorm_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(brainstorm_parser, "Session id; defaults to current session")
    brainstorm_parser.add_argument(
        "--max-candidates",
        type=int,
        default=5,
        help="Maximum candidate directions to request",
    )
    brainstorm_parser.add_argument(
        "--apply",
        action="store_true",
        help="Append generated task and decision candidates to the current run",
    )

    run_parser = subcommands.add_parser(
        "run",
        aliases=["/run"],
        help="Plan, execute, repair, review, and report",
    )
    run_parser.add_argument("goal", nargs="?", help="Natural-language goal")
    run_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(
        run_parser,
        "Existing session id to continue; defaults to current session",
    )
    run_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum run loop iterations",
    )
    run_parser.add_argument(
        "--max-tasks-per-iteration",
        type=int,
        default=1,
        help="Tasks to execute per iteration",
    )

    resume_parser = subcommands.add_parser(
        "resume",
        aliases=["/resume"],
        help="Resume a paused run after decisions",
    )
    resume_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(resume_parser, "Session id; defaults to current session")
    resume_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum run loop iterations",
    )
    resume_parser.add_argument(
        "--max-tasks-per-iteration",
        type=int,
        default=1,
        help="Tasks to execute per iteration",
    )

    compact_parser = subcommands.add_parser(
        "compact",
        aliases=["/compact"],
        help="Create a context snapshot",
    )
    compact_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(compact_parser, "Session id to compact; defaults to current session")
    compact_parser.add_argument(
        "--focus",
        default="manual context compaction",
        help="Snapshot focus",
    )

    handoff_parser = subcommands.add_parser(
        "handoff",
        aliases=["/handoff"],
        help="Create a handoff package for another agent or a future run",
    )
    handoff_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(handoff_parser, "Session id to hand off; defaults to current session")
    handoff_parser.add_argument(
        "--to",
        dest="to_role",
        default="FutureRun",
        help="Target role for the handoff package",
    )
    handoff_parser.add_argument(
        "--from-agent-id",
        default=None,
        help="Optional source agent identifier",
    )
    handoff_parser.add_argument(
        "--next-command",
        default=None,
        help="Recommended next command; inferred when omitted",
    )
    handoff_parser.add_argument(
        "--focus",
        default=None,
        help="Optional snapshot focus override",
    )

    execute_parser = subcommands.add_parser(
        "execute",
        aliases=["/execute"],
        help="Execute ready tasks from a planned run",
    )
    execute_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(execute_parser, "Session id to execute; defaults to current session")
    execute_parser.add_argument(
        "--max-tasks",
        type=int,
        default=1,
        help="Maximum ready tasks to execute",
    )

    debug_parser = subcommands.add_parser(
        "debug",
        aliases=["/debug"],
        help="Repair blocked tasks from a run",
    )
    debug_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(debug_parser, "Session id to debug; defaults to current session")
    debug_parser.add_argument("--task-id", default=None, help="Specific blocked task to repair")
    debug_parser.add_argument(
        "--max-repairs",
        type=int,
        default=1,
        help="Maximum blocked tasks to repair",
    )

    review_parser = subcommands.add_parser(
        "review",
        aliases=["/review"],
        help="Evaluate a run and write review reports",
    )
    review_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(review_parser, "Session id to review; defaults to current session")

    decide_parser = subcommands.add_parser(
        "decide",
        aliases=["/decide"],
        help="Create, list, or resolve user decision points",
    )
    decide_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(decide_parser, "Session id; defaults to current session")
    decide_parser.add_argument("--question", default=None, help="Decision question for creation")
    decide_parser.add_argument("--options-json", default=None, help="JSON array of options")
    decide_parser.add_argument(
        "--recommended-option-id",
        default=None,
        help="Recommended option id",
    )
    decide_parser.add_argument("--default-option-id", default=None, help="Default option id")
    decide_parser.add_argument("--impact-json", default=None, help="JSON impact object")
    decide_parser.add_argument(
        "--decision-id",
        default=None,
        help="Decision id to create or resolve",
    )
    decide_parser.add_argument(
        "--select-option-id",
        default=None,
        help="Resolve with this option id",
    )
    decide_parser.add_argument(
        "--use-default",
        action="store_true",
        help="Resolve with default option",
    )
    decide_parser.add_argument("--list-pending", action="store_true", help="List pending decisions")

    acceptance_parser = subcommands.add_parser(
        "acceptance",
        aliases=["/acceptance"],
        help="Run reproducible runtime acceptance scenarios",
    )
    acceptance_parser.add_argument("--root", default=".", help="Acceptance workspace root")
    acceptance_parser.add_argument(
        "--suite",
        choices=["smoke", "core", "advanced", "offline"],
        default="smoke",
        help="Acceptance scenario suite",
    )
    acceptance_parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Specific scenario to run; can be repeated and overrides --suite",
    )
    acceptance_parser.add_argument(
        "--summary-json", type=Path, default=None, help="Write JSON summary"
    )
    acceptance_parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow fake/offline provider scenarios",
    )
    acceptance_parser.add_argument(
        "--cleanup", action="store_true", help="Remove generated workspace on success"
    )
    acceptance_parser.add_argument(
        "--run-attempts", type=int, default=2, help="Run attempts per scenario"
    )
    acceptance_parser.add_argument(
        "--model-max-retries",
        type=int,
        default=5,
        help="Model retry attempts inside smoke scenarios",
    )
    acceptance_parser.add_argument(
        "--scenario-timeout-seconds",
        type=int,
        default=1200,
        help="Maximum seconds per scenario",
    )
    acceptance_parser.add_argument(
        "--promote-failures",
        action="store_true",
        help="Turn failed acceptance scenarios into ready tasks on the current session",
    )
    acceptance_parser.add_argument(
        "--run-promoted",
        action="store_true",
        help="After promoting failures, continue the current session run loop",
    )
    acceptance_parser.add_argument(
        "--rerun-promoted",
        action="store_true",
        help="After running promoted failure tasks, rerun only those promoted scenarios",
    )
    acceptance_parser.add_argument(
        "--promoted-run-max-iterations",
        type=int,
        default=None,
        help="Maximum run-loop iterations when --run-promoted is used",
    )
    acceptance_parser.add_argument(
        "--promoted-run-max-tasks-per-iteration",
        type=int,
        default=1,
        help="Tasks per execute pass when --run-promoted is used",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command.lstrip("/")

    if command == "init":
        init_result = InitCommand(
            root=Path(args.root),
            profile=args.profile,
            force=args.force,
        ).run()
        print(init_result.to_text())
        return

    if command == "model-check":
        model_result = ModelCheckCommand(root=Path(args.root), skip_call=args.skip_call).run()
        print(model_result.to_text())
        return

    if command == "plan":
        plan_result = PlanCommand(root=Path(args.root), goal=args.goal).run()
        print(plan_result.to_text())
        return

    if command == "new":
        new_result = NewCommand(root=Path(args.root), goal=args.goal).run()
        print(new_result.to_text())
        return

    if command in {"sessions", "runs", "history"}:
        sessions_result = SessionsCommand(
            root=Path(args.root),
            session_id=args.session_id,
            set_current=args.set_current,
            limit=args.limit,
        ).run()
        print(sessions_result.to_text())
        return

    if command == "research":
        research_result = ResearchCommand(
            root=Path(args.root),
            query=args.query,
            run_id=args.session_id,
            urls=args.url,
            use_local=not args.no_local,
            use_serper=args.serper,
            max_sources=args.max_sources,
        ).run()
        print(research_result.to_text())
        return

    if command == "brainstorm":
        brainstorm_result = BrainstormCommand(
            root=Path(args.root),
            goal=args.goal,
            run_id=args.session_id,
            max_candidates=args.max_candidates,
            apply=args.apply,
        ).run()
        print(brainstorm_result.to_text())
        return

    if command == "run":
        run_result = RunCommand(
            root=Path(args.root),
            goal=args.goal,
            run_id=args.session_id,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
        ).run()
        print(run_result.to_text())
        return

    if command == "resume":
        resume_result = ResumeCommand(
            root=Path(args.root),
            run_id=args.session_id,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
        ).run()
        print(resume_result.to_text())
        return

    if command == "compact":
        compact_result = CompactCommand(
            root=Path(args.root),
            run_id=args.session_id,
            focus=args.focus,
        ).run()
        print(compact_result.to_text())
        return

    if command == "handoff":
        handoff_result = HandoffCommand(
            root=Path(args.root),
            run_id=args.session_id,
            to_role=args.to_role,
            from_agent_id=args.from_agent_id,
            recommended_next_command=args.next_command,
            focus=args.focus,
        ).run()
        print(handoff_result.to_text())
        return

    if command == "execute":
        execute_result = ExecuteCommand(
            root=Path(args.root),
            run_id=args.session_id,
            max_tasks=args.max_tasks,
        ).run()
        print(execute_result.to_text())
        return

    if command == "debug":
        debug_result = DebugCommand(
            root=Path(args.root),
            run_id=args.session_id,
            task_id=args.task_id,
            max_repairs=args.max_repairs,
        ).run()
        print(debug_result.to_text())
        return

    if command == "review":
        review_result = ReviewCommand(root=Path(args.root), run_id=args.session_id).run()
        print(review_result.to_text())
        return

    if command == "decide":
        decide_result = DecideCommand(
            root=Path(args.root),
            run_id=args.session_id,
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

    if command == "acceptance":
        acceptance_result = AcceptanceCommand(
            root=Path(args.root),
            suite=args.suite,
            scenarios=args.scenario,
            summary_json=args.summary_json,
            allow_fake=args.allow_fake,
            cleanup=args.cleanup,
            run_attempts=args.run_attempts,
            model_max_retries=args.model_max_retries,
            scenario_timeout_seconds=args.scenario_timeout_seconds,
            promote_failures=args.promote_failures,
            run_promoted=args.run_promoted,
            rerun_promoted=args.rerun_promoted,
            promoted_run_max_iterations=args.promoted_run_max_iterations,
            promoted_run_max_tasks_per_iteration=args.promoted_run_max_tasks_per_iteration,
        ).run()
        print(acceptance_result.to_text())
        if not acceptance_result.ok:
            raise SystemExit(acceptance_result.returncode)
        return

    parser.error(f"Unsupported command: {args.command}")
