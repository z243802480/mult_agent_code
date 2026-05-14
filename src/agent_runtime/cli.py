from __future__ import annotations

import argparse
from pathlib import Path

from agent_runtime.commands.acceptance_command import AcceptanceCommand
from agent_runtime.commands.acceptance_gate_command import AcceptanceGateCommand
from agent_runtime.commands.acceptance_history_command import AcceptanceHistoryCommand
from agent_runtime.commands.brainstorm_command import BrainstormCommand
from agent_runtime.commands.capability_report_command import CapabilityReportCommand
from agent_runtime.commands.daily_command import (
    DailyPlanCommand,
    DailyReportCommand,
    DailyRunCommand,
)
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.model_check_command import ModelCheckCommand
from agent_runtime.commands.new_command import NewCommand
from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.debug_command import DebugCommand
from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.handoff_command import HandoffCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.replan_command import ReplanCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.commands.roadmap_command import RoadmapCommand
from agent_runtime.commands.review_command import ReviewCommand
from agent_runtime.commands.run_command import RunCommand
from agent_runtime.commands.resume_command import ResumeCommand
from agent_runtime.commands.sessions_command import SessionsCommand
from agent_runtime.commands.verification_command import VerificationStatusCommand
from agent_runtime.commands.weekly_report_command import WeeklyReportCommand


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
    model_parser.add_argument(
        "--tier",
        choices=["strong", "medium", "cheap"],
        default="cheap",
        help="Model tier route to validate",
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
    sessions_parser.add_argument(
        "--context",
        action="store_true",
        help="Include latest snapshot and handoff recovery context",
    )

    verification_parser = subcommands.add_parser(
        "verification",
        aliases=["/verification", "verify-status", "/verify-status"],
        help="Show the latest local verification summary",
    )
    verification_parser.add_argument("--root", default=".", help="Workspace root path")

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
    run_parser.add_argument(
        "--no-research",
        action="store_true",
        help="Skip the pre-planning research pass for clear or cost-sensitive goals",
    )
    run_parser.add_argument(
        "--parallel-disjoint-writes",
        action="store_true",
        help="Allow /run to execute readonly and disjoint write-scope tasks concurrently",
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
    resume_parser.add_argument(
        "--parallel-disjoint-writes",
        action="store_true",
        help="Allow /resume to execute readonly and disjoint write-scope tasks concurrently",
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
    execute_parser.add_argument(
        "--parallel-readonly",
        action="store_true",
        help="Execute readonly ready tasks concurrently; write tasks remain serial",
    )
    execute_parser.add_argument(
        "--parallel-disjoint-writes",
        action="store_true",
        help="Execute readonly and disjoint write-scope tasks concurrently through isolated candidate workspaces",
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

    replan_parser = subcommands.add_parser(
        "replan",
        aliases=["/replan"],
        help="Turn task failure evidence into repair tasks or decision points",
    )
    replan_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(replan_parser, "Session id to replan; defaults to current session")
    replan_parser.add_argument(
        "--max-items",
        type=int,
        default=2,
        help="Maximum failure evidence items to process",
    )
    replan_parser.add_argument(
        "--max-replans-per-task",
        type=int,
        default=2,
        help="Create a decision point after this many replans for one task",
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
        choices=["smoke", "core", "advanced", "nightly", "offline"],
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
        "--failed-only",
        action="store_true",
        help="Run only scenarios that failed in the latest acceptance report",
    )
    acceptance_parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Directory for scenario workspaces; defaults to .agent/acceptance/workspaces/<run>",
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
    acceptance_parser.add_argument(
        "--fail-on-trend-warning",
        action="store_true",
        help="Exit non-zero when acceptance trend warnings are present",
    )
    acceptance_parser.add_argument(
        "--warn-model-call-delta",
        type=int,
        default=5,
        help="Warn when model calls increase by this amount",
    )
    acceptance_parser.add_argument(
        "--warn-duration-delta",
        type=float,
        default=120.0,
        help="Warn when duration increases by this many seconds",
    )
    acceptance_parser.add_argument(
        "--warn-repair-delta",
        type=int,
        default=1,
        help="Warn when repair attempts increase by this amount",
    )
    acceptance_parser.add_argument(
        "--warn-context-compaction-delta",
        type=int,
        default=1,
        help="Warn when context compactions increase by this amount",
    )

    acceptance_history_parser = subcommands.add_parser(
        "acceptance-history",
        aliases=["/acceptance-history", "acceptance-trend", "/acceptance-trend"],
        help="Show persisted acceptance history and trend deltas",
    )
    acceptance_history_parser.add_argument("--root", default=".", help="Workspace root path")
    acceptance_history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum history entries to show",
    )
    acceptance_history_parser.add_argument(
        "--suite",
        default=None,
        help="Only show entries for this suite",
    )
    acceptance_history_parser.add_argument(
        "--history-jsonl",
        type=Path,
        default=None,
        help="Read history from a custom JSONL path",
    )
    acceptance_history_parser.add_argument(
        "--warn-model-call-delta",
        type=int,
        default=5,
        help="Warn when model calls increase by this amount",
    )
    acceptance_history_parser.add_argument(
        "--warn-duration-delta",
        type=float,
        default=120.0,
        help="Warn when duration increases by this many seconds",
    )
    acceptance_history_parser.add_argument(
        "--warn-repair-delta",
        type=int,
        default=1,
        help="Warn when repair attempts increase by this amount",
    )
    acceptance_history_parser.add_argument(
        "--warn-context-compaction-delta",
        type=int,
        default=1,
        help="Warn when context compactions increase by this amount",
    )
    acceptance_history_parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit non-zero when trend warnings are present",
    )

    acceptance_gate_parser = subcommands.add_parser(
        "acceptance-gate",
        aliases=["/acceptance-gate", "release-gate", "/release-gate"],
        help="Evaluate the latest acceptance report as a release gate",
    )
    acceptance_gate_parser.add_argument("--root", default=".", help="Workspace root path")
    acceptance_gate_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Acceptance report path; defaults to .agent/acceptance/acceptance_report.json",
    )
    acceptance_gate_parser.add_argument(
        "--suite",
        default=None,
        help="Require the report to belong to this suite",
    )
    acceptance_gate_parser.add_argument(
        "--min-scenarios",
        type=int,
        default=1,
        help="Minimum scenario count required for the gate",
    )
    acceptance_gate_parser.add_argument(
        "--min-capabilities",
        type=int,
        default=None,
        help="Minimum passed capability count required for the gate",
    )
    acceptance_gate_parser.add_argument(
        "--require-tier",
        action="append",
        default=[],
        help="Required acceptance tier; can be repeated",
    )
    acceptance_gate_parser.add_argument(
        "--allow-trend-warnings",
        action="store_true",
        help="Do not fail the gate when trend warnings are present",
    )
    acceptance_gate_parser.add_argument(
        "--no-require-repair-closure",
        action="store_true",
        help="Do not require a successful rerun closure when the base acceptance failed",
    )
    acceptance_gate_parser.add_argument(
        "--no-require-runtime-os",
        action="store_true",
        help="Do not require Runtime OS worker/profile/merge evidence for core release gates",
    )
    capability_report_parser = subcommands.add_parser(
        "capability-report",
        aliases=["/capability-report", "capabilities", "/capabilities"],
        help="Summarize acceptance trends, failures, repair rounds, and cost signals",
    )
    capability_report_parser.add_argument("--root", default=".", help="Workspace root path")
    capability_report_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum acceptance history entries to include",
    )
    weekly_report_parser = subcommands.add_parser(
        "weekly-report",
        aliases=["/weekly-report", "production-report", "/production-report"],
        help="Summarize long-run cycles, acceptance, model capability, and weekly risks",
    )
    weekly_report_parser.add_argument("--root", default=".", help="Workspace root path")
    weekly_report_parser.add_argument("--week-id", default=None, help="Week id such as 2026-W20")
    weekly_report_parser.add_argument(
        "--limit",
        type=int,
        default=7,
        help="Maximum long-run and acceptance records to include",
    )
    roadmap_parser = subcommands.add_parser(
        "roadmap-update",
        aliases=["/roadmap-update", "prd-update", "/prd-update"],
        help="Update project roadmap and PRD-style Markdown from runtime evidence",
    )
    roadmap_parser.add_argument("--root", default=".", help="Workspace root path")
    roadmap_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown output path; defaults to docs/zh/自动路线图.md",
    )
    daily_plan_parser = subcommands.add_parser(
        "daily-plan",
        aliases=["/daily-plan", "long-run-plan", "/long-run-plan"],
        help="Create a bounded long-run production cycle plan",
    )
    daily_plan_parser.add_argument("--root", default=".", help="Workspace root path")
    daily_plan_parser.add_argument("--date", default=None, help="Legacy plan date, default today")
    daily_plan_parser.add_argument(
        "--cycle-id",
        default=None,
        help="Long-run cycle id; overrides --date when provided",
    )
    daily_plan_parser.add_argument(
        "--objective",
        default=None,
        help="Long-running objective this cycle should advance",
    )
    daily_plan_parser.add_argument("--max-model-calls", type=int, default=20)
    daily_plan_parser.add_argument("--max-tool-calls", type=int, default=60)
    daily_plan_parser.add_argument("--max-runtime-minutes", type=int, default=60)
    daily_plan_parser.add_argument("--max-repair-attempts", type=int, default=2)

    daily_run_parser = subcommands.add_parser(
        "daily-run",
        aliases=["/daily-run", "long-run", "/long-run"],
        help="Run or stage a bounded long-run production cycle",
    )
    daily_run_parser.add_argument("--root", default=".", help="Workspace root path")
    daily_run_parser.add_argument("--date", default=None, help="Legacy run date, default today")
    daily_run_parser.add_argument(
        "--cycle-id",
        default=None,
        help="Long-run cycle id; overrides --date when provided",
    )
    daily_run_parser.add_argument(
        "--objective",
        default=None,
        help="Long-running objective this cycle should advance",
    )
    daily_run_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute selected daily actions; omitted means plan-only safe mode",
    )
    daily_run_parser.add_argument("--max-actions", type=int, default=1)
    daily_run_parser.add_argument("--max-model-calls", type=int, default=20)
    daily_run_parser.add_argument("--max-tool-calls", type=int, default=60)
    daily_run_parser.add_argument("--max-runtime-minutes", type=int, default=60)
    daily_run_parser.add_argument("--max-repair-attempts", type=int, default=2)

    daily_report_parser = subcommands.add_parser(
        "daily-report",
        aliases=["/daily-report", "long-run-report", "/long-run-report"],
        help="Show or create a long-run production cycle report",
    )
    daily_report_parser.add_argument("--root", default=".", help="Workspace root path")
    daily_report_parser.add_argument("--date", default=None, help="Legacy report date, default today")
    daily_report_parser.add_argument(
        "--cycle-id",
        default=None,
        help="Long-run cycle id; overrides --date when provided",
    )
    daily_report_parser.add_argument(
        "--objective",
        default=None,
        help="Long-running objective this cycle should describe",
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
        model_result = ModelCheckCommand(
            root=Path(args.root),
            skip_call=args.skip_call,
            model_tier=args.tier,
        ).run()
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
            include_context=args.context,
        ).run()
        print(sessions_result.to_text())
        return

    if command in {"verification", "verify-status"}:
        verification_result = VerificationStatusCommand(root=Path(args.root)).run()
        print(verification_result.to_text())
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
            enable_research=not args.no_research,
            parallel_writes=args.parallel_disjoint_writes,
        ).run()
        print(run_result.to_text())
        return

    if command == "resume":
        resume_result = ResumeCommand(
            root=Path(args.root),
            run_id=args.session_id,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
            parallel_writes=args.parallel_disjoint_writes,
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
            parallel_readonly=args.parallel_readonly,
            parallel_writes=args.parallel_disjoint_writes,
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

    if command == "replan":
        replan_result = ReplanCommand(
            root=Path(args.root),
            run_id=args.session_id,
            max_items=args.max_items,
            max_replans_per_task=args.max_replans_per_task,
        ).run()
        print(replan_result.to_text())
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
            failed_only=args.failed_only,
            workspace_root=args.workspace_root,
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
            fail_on_trend_warning=args.fail_on_trend_warning,
            warn_model_call_delta=args.warn_model_call_delta,
            warn_duration_delta=args.warn_duration_delta,
            warn_repair_delta=args.warn_repair_delta,
            warn_context_compaction_delta=args.warn_context_compaction_delta,
        ).run()
        print(acceptance_result.to_text())
        if not acceptance_result.ok:
            raise SystemExit(acceptance_result.returncode)
        return

    if command in {"acceptance-history", "acceptance-trend"}:
        acceptance_history_result = AcceptanceHistoryCommand(
            root=Path(args.root),
            limit=args.limit,
            suite=args.suite,
            history_jsonl=args.history_jsonl,
            warn_model_call_delta=args.warn_model_call_delta,
            warn_duration_delta=args.warn_duration_delta,
            warn_repair_delta=args.warn_repair_delta,
            warn_context_compaction_delta=args.warn_context_compaction_delta,
        ).run()
        print(acceptance_history_result.to_text())
        if args.fail_on_warning and acceptance_history_result.warnings:
            raise SystemExit(1)
        return

    if command in {"acceptance-gate", "release-gate"}:
        acceptance_gate_result = AcceptanceGateCommand(
            root=Path(args.root),
            report_path=args.report,
            suite=args.suite,
            min_scenarios=args.min_scenarios,
            min_capabilities=args.min_capabilities,
            require_tiers=args.require_tier,
            allow_trend_warnings=args.allow_trend_warnings,
            require_repair_closure=not args.no_require_repair_closure,
            require_runtime_os=False if args.no_require_runtime_os else None,
        ).run()
        print(acceptance_gate_result.to_text())
        if not acceptance_gate_result.ok:
            raise SystemExit(1)
        return

    if command in {"capability-report", "capabilities"}:
        capability_report_result = CapabilityReportCommand(
            root=Path(args.root),
            limit=args.limit,
        ).run()
        print(capability_report_result.to_text())
        return

    if command in {"weekly-report", "production-report"}:
        weekly_report_result = WeeklyReportCommand(
            root=Path(args.root),
            week_id=args.week_id,
            limit=args.limit,
        ).run()
        print(weekly_report_result.to_text())
        return

    if command in {"roadmap-update", "prd-update"}:
        roadmap_result = RoadmapCommand(
            root=Path(args.root),
            output=args.output,
        ).run()
        print(roadmap_result.to_text())
        return

    if command in {"daily-plan", "long-run-plan"}:
        daily_plan_result = DailyPlanCommand(
            root=Path(args.root),
            date=args.cycle_id or args.date,
            max_model_calls=args.max_model_calls,
            max_tool_calls=args.max_tool_calls,
            max_runtime_minutes=args.max_runtime_minutes,
            max_repair_attempts=args.max_repair_attempts,
            objective=args.objective,
        ).run()
        print(daily_plan_result.to_text())
        return

    if command in {"daily-run", "long-run"}:
        daily_run_result = DailyRunCommand(
            root=Path(args.root),
            date=args.cycle_id or args.date,
            execute=args.execute,
            max_actions=args.max_actions,
            max_model_calls=args.max_model_calls,
            max_tool_calls=args.max_tool_calls,
            max_runtime_minutes=args.max_runtime_minutes,
            max_repair_attempts=args.max_repair_attempts,
            objective=args.objective,
        ).run()
        print(daily_run_result.to_text())
        return

    if command in {"daily-report", "long-run-report"}:
        daily_report_result = DailyReportCommand(
            root=Path(args.root),
            date=args.cycle_id or args.date,
            objective=args.objective,
        ).run()
        print(daily_report_result.to_text())
        return

    parser.error(f"Unsupported command: {args.command}")
