from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from asteria_runtime import __version__
from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.acceptance_command import AcceptanceCommand
from asteria_runtime.commands.acceptance_gate_command import AcceptanceGateCommand
from asteria_runtime.commands.acceptance_history_command import AcceptanceHistoryCommand
from asteria_runtime.commands.brainstorm_command import BrainstormCommand
from asteria_runtime.commands.capability_report_command import CapabilityReportCommand
from asteria_runtime.commands.chat_command import ChatCommand
from asteria_runtime.commands.compact_command import CompactCommand
from asteria_runtime.commands.daily_command import (
    DailyPlanCommand,
    DailyReportCommand,
    DailyRunCommand,
)
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.model_check_command import ModelCheckCommand
from asteria_runtime.commands.new_command import NewCommand
from asteria_runtime.commands.ops_signal_command import OpsSignalCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.evidence_bundle_command import EvidenceBundleCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.gate_command import GateCommand
from asteria_runtime.commands.validation_command import ValidationCommand
from asteria_runtime.commands.validation_run_command import ValidationRunCommand
from asteria_runtime.commands.handoff_command import HandoffCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.plugins_command import PluginsCommand
from asteria_runtime.commands.promotions_command import PromotionsCommand
from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.commands.research_command import ResearchCommand
from asteria_runtime.commands.roadmap_command import RoadmapCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand
from asteria_runtime.commands.verification_command import VerificationStatusCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.commands.weekly_report_command import WeeklyReportCommand
from asteria_runtime.real_model_acceptance import SCENARIOS as REAL_MODEL_SCENARIOS
from asteria_runtime.real_model_acceptance import SUITES as REAL_MODEL_SUITES
from asteria_runtime.real_model_acceptance import run_from_args as run_real_model_acceptance
from asteria_runtime.real_model_gate import run_from_args as run_real_model_gate
from asteria_runtime.real_model_smoke import run_from_args as run_real_model_smoke


CommandGroup = tuple[str, str, list[tuple[str, str]]]
PERMISSION_LEVEL_HELP = (
    "User-facing permission mode: ask_everything asks every operation, reviewed_auto "
    "allows low-risk work and asks for sensitive actions, auto advances within runtime "
    "hard guards. Legacy aliases ask/balanced/auto remain accepted."
)
MODEL_STRATEGY_HELP = (
    "User-facing model strategy: auto routes by task, quality favors stronger models, "
    "economy favors cheaper models, local is reserved for privacy-first local routes."
)
SLASH_ALIAS_HELP = (
    "Compatibility: slash-prefixed command forms such as `asteria /run` remain aliases "
    "for older automation; use plain command names in new docs and scripts."
)
ACCEPT_VS_ACCEPTANCE_HELP = (
    "`accept` finalizes one reviewed run; `acceptance` runs validation suites for "
    "maintainers and CI."
)
MAINTAINER_COMMAND_HELP = (
    "Maintainer/CI command: use after the default init -> run -> status -> resume -> "
    "review -> accept workflow, not as an ordinary completion step."
)


class AsteriaArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._command_groups: list[CommandGroup] = []

    def set_command_groups(self, groups: list[CommandGroup]) -> None:
        self._command_groups = groups

    def format_help(self) -> str:
        if self.prog != "asteria" or not self._command_groups:
            return super().format_help()

        lines = [
            "usage: asteria [-h] [--version] <command> ...",
            "",
            "Asteria runtime CLI",
            "",
            "Start",
            "  Product workflow commands for ordinary goal -> progress -> review journeys.",
        ]
        for title, description, commands in self._command_groups:
            if title != "Start":
                lines.extend(["", title, f"  {description}"])
            width = max(len(command) for command, _summary in commands)
            for command, summary in commands:
                lines.append(f"  {command.ljust(width)}  {summary}")
        lines.extend(
            [
                "",
                "Options",
                "  -h, --help  show this help message and exit",
                "  --version   show runtime version and exit",
                "",
                "Compatibility",
                f"  {SLASH_ALIAS_HELP}",
                "",
                "Accept vs acceptance",
                f"  {ACCEPT_VS_ACCEPTANCE_HELP}",
                "",
                "Maintainer commands",
                f"  {MAINTAINER_COMMAND_HELP}",
                "",
                "Use `asteria <command> --help` for command-specific options.",
            ]
        )
        return "\n".join(lines) + "\n"


def add_session_id_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "--session-id",
        "--run-id",
        dest="session_id",
        default=None,
        help=help_text,
    )


def add_workspace_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input-root",
        action="append",
        default=[],
        help="Input directory to mount for planning; repeat for multi-project goals",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Directory where user-facing outputs should be written",
    )
    parser.add_argument(
        "--artifact-root",
        default=None,
        help="Directory for generated reports, exports, and runtime-managed artifacts",
    )
    parser.add_argument(
        "--worktree-policy",
        choices=["controlled_patch", "worktree", "isolated_copy"],
        default="controlled_patch",
        help="Candidate workspace strategy for later execution",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = AsteriaArgumentParser(prog="asteria", description="Asteria runtime CLI")
    parser.add_argument(
        "--version",
        action="version",
        version=f"asteria-runtime {__version__}",
        help="Show runtime version and exit",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    version_parser = subcommands.add_parser(
        "version",
        aliases=["/version"],
        help="Show runtime version and packaging diagnostics",
    )
    version_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    init_parser = subcommands.add_parser(
        "init",
        aliases=["/init"],
        help="Initialize an agent-ready workspace",
        epilog=SLASH_ALIAS_HELP,
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
    model_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    plan_parser = subcommands.add_parser(
        "plan",
        aliases=["/plan"],
        help="Read-only comprehensive plan; analyze but do not execute user work",
    )
    plan_parser.add_argument("goal", help="Natural-language goal")
    plan_parser.add_argument("--root", default=".", help="Workspace root path")
    add_workspace_selection_arguments(plan_parser)
    plan_parser.add_argument(
        "--permission-level",
        choices=["ask", "balanced", "auto", "ask_everything", "reviewed_auto"],
        default="ask",
        help=PERMISSION_LEVEL_HELP,
    )
    plan_parser.add_argument(
        "--model-strategy",
        choices=["auto", "quality", "economy", "local"],
        default="auto",
        help=MODEL_STRATEGY_HELP,
    )

    chat_parser = subcommands.add_parser(
        "chat",
        aliases=["/chat"],
        help="Lightweight Q&A mode; no state-changing project work",
    )
    chat_parser.add_argument("question", help="Question or short request")
    chat_parser.add_argument("--root", default=".", help="Workspace root path")
    chat_parser.add_argument(
        "--permission-level",
        choices=["ask", "balanced", "auto", "ask_everything", "reviewed_auto"],
        default="balanced",
        help=PERMISSION_LEVEL_HELP,
    )
    chat_parser.add_argument(
        "--model-strategy",
        choices=["auto", "quality", "economy", "local"],
        default="auto",
        help=MODEL_STRATEGY_HELP,
    )
    chat_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

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

    status_parser = subcommands.add_parser(
        "status",
        aliases=["/status"],
        help="Show current Runtime OS control surface status",
        epilog=SLASH_ALIAS_HELP,
    )
    status_parser.add_argument("--root", default=".", help="Workspace root path")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    status_parser.add_argument(
        "--debug",
        action="store_true",
        help="Show runtime diagnostics instead of the user-facing active goal memory",
    )

    doctor_parser = subcommands.add_parser(
        "doctor",
        aliases=["/doctor"],
        help="Check local runtime setup without running model calls",
    )
    doctor_parser.add_argument("--root", default=".", help="Workspace root path")
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    gate_status_parser = subcommands.add_parser(
        "gate-status",
        aliases=["/gate-status"],
        help="Show real model gate, validation suite, and core acceptance validation",
    )
    gate_status_parser.add_argument("--root", default=".", help="Workspace root path")
    gate_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    gate_parser = subcommands.add_parser(
        "gate",
        aliases=["/gate"],
        help="Run read-only staged release checks for package, doctor, and gate status",
        epilog=f"{MAINTAINER_COMMAND_HELP} {SLASH_ALIAS_HELP}",
    )
    gate_parser.add_argument("--root", default=".", help="Workspace root path")
    gate_parser.add_argument(
        "--stage",
        choices=["read-only", "release"],
        default="read-only",
        help="Gate stage to run",
    )
    gate_parser.add_argument("--report", type=Path, default=None, help="Acceptance report path")
    gate_parser.add_argument("--suite", default="core", help="Acceptance suite name")
    gate_parser.add_argument(
        "--skip-lint", action="store_true", help="Skip ruff lint check in release stage"
    )
    gate_parser.add_argument(
        "--skip-typecheck", action="store_true", help="Skip mypy type check in release stage"
    )
    gate_parser.add_argument(
        "--skip-tests", action="store_true", help="Skip pytest run in release stage"
    )
    gate_parser.add_argument(
        "--skip-acceptance-gate",
        action="store_true",
        help="Skip acceptance-gate check in release stage",
    )
    gate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    real_model_smoke_parser = subcommands.add_parser(
        "real-model-smoke",
        aliases=["/real-model-smoke"],
        help="Run a real model end-to-end smoke test in an isolated workspace",
    )
    real_model_smoke_parser.add_argument("--root", type=Path, default=None)
    real_model_smoke_parser.add_argument(
        "--goal",
        default="Create a local file hello_runtime.txt containing one line: real model smoke ok",
    )
    real_model_smoke_parser.add_argument("--expected-file", default="hello_runtime.txt")
    real_model_smoke_parser.add_argument("--expected-text", default="real model smoke ok")
    real_model_smoke_parser.add_argument("--max-iterations", type=int, default=3)
    real_model_smoke_parser.add_argument("--max-tasks-per-iteration", type=int, default=1)
    real_model_smoke_parser.add_argument("--run-attempts", type=int, default=1)
    real_model_smoke_parser.add_argument("--model-max-retries", type=int, default=1)
    real_model_smoke_parser.add_argument("--command-timeout-seconds", type=int, default=900)
    real_model_smoke_parser.add_argument("--python", default=sys.executable)
    real_model_smoke_parser.add_argument("--summary-json", type=Path, default=None)
    real_model_smoke_parser.add_argument("--matrix", choices=["p0"], default=None)
    real_model_smoke_parser.add_argument("--matrix-case", action="append", default=[])
    real_model_smoke_parser.add_argument("--matrix-output-dir", type=Path, default=None)
    real_model_smoke_parser.add_argument("--allow-fake", action="store_true")
    real_model_smoke_parser.add_argument("--no-recovery", action="store_true")
    real_model_smoke_parser.add_argument("--recovery-rounds", type=int, default=2)
    real_model_smoke_parser.add_argument("--cleanup", action="store_true")
    real_model_smoke_parser.add_argument("--no-research", action="store_true")

    real_model_gate_parser = subcommands.add_parser(
        "real-model-gate",
        aliases=["/real-model-gate"],
        help="Run the controlled real-model gate before release validation",
    )
    real_model_gate_parser.add_argument("--root", type=Path, default=None)
    real_model_gate_parser.add_argument("--summary-json", type=Path, default=None)
    real_model_gate_parser.add_argument("--python", default=sys.executable)
    real_model_gate_parser.add_argument("--allow-fake", action="store_true")
    real_model_gate_parser.add_argument("--cleanup", action="store_true")
    real_model_gate_parser.add_argument("--smoke-run-attempts", type=int, default=1)
    real_model_gate_parser.add_argument("--command-timeout-seconds", type=int, default=900)

    real_model_acceptance_parser = subcommands.add_parser(
        "real-model-acceptance",
        aliases=["/real-model-acceptance"],
        help="Run curated real-model acceptance scenarios in isolated workspaces",
    )
    real_model_acceptance_parser.add_argument(
        "--suite", choices=sorted(REAL_MODEL_SUITES), default="smoke"
    )
    real_model_acceptance_parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(REAL_MODEL_SCENARIOS),
        default=[],
    )
    real_model_acceptance_parser.add_argument("--root", type=Path, default=None)
    real_model_acceptance_parser.add_argument("--summary-json", type=Path, default=None)
    real_model_acceptance_parser.add_argument("--history-jsonl", type=Path, default=None)
    real_model_acceptance_parser.add_argument("--python", default=sys.executable)
    real_model_acceptance_parser.add_argument("--allow-fake", action="store_true")
    real_model_acceptance_parser.add_argument("--run-attempts", type=int, default=1)
    real_model_acceptance_parser.add_argument("--model-max-retries", type=int, default=1)
    real_model_acceptance_parser.add_argument("--scenario-timeout-seconds", type=int, default=600)
    real_model_acceptance_parser.add_argument("--cleanup", action="store_true")
    real_model_acceptance_parser.add_argument("--reuse-workspace", action="store_true")

    validation_run_parser = subcommands.add_parser(
        "validation-run",
        aliases=["/validation-run"],
        help="Run a controlled small real-task validation after release gates pass",
    )
    validation_run_parser.add_argument(
        "goal",
        nargs="?",
        default=None,
        help="Small real-task goal; defaults to a tiny file artifact probe",
    )
    validation_run_parser.add_argument("--root", default=".", help="Workspace root path")
    validation_run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check preflight and write a validation-run plan summary",
    )
    validation_run_parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum run-loop iterations for the validation task",
    )
    validation_run_parser.add_argument(
        "--max-tasks-per-iteration",
        type=int,
        default=1,
        help="Maximum tasks executed per iteration",
    )
    validation_run_parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Write the validation-run summary to this JSON path",
    )
    validation_run_parser.add_argument(
        "--probe-id",
        action="append",
        choices=[
            "parent_selects_subagent",
            "readonly_fanout_succeeds",
            "readonly_write_tool_blocked",
            "disjoint_write_gate_blocks_unsafe_fanout",
            "parent_loop_stops_after_observation",
            "repair_replan_path",
            "ask_stop_path",
            "context_pressure_path",
            "capability_selection_path",
        ],
        default=[],
        help="Target a specific validation probe; repeat for multiple scoped probes",
    )
    validation_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    validation_parser = subcommands.add_parser(
        "validation",
        aliases=["/validation"],
        help="Prepare a dry-run validation plan without changing candidate writes",
        epilog=f"{MAINTAINER_COMMAND_HELP} {SLASH_ALIAS_HELP}",
    )
    validation_parser.add_argument(
        "goal",
        nargs="?",
        default=None,
        help="Small real-task goal; defaults to the validation artifact probe",
    )
    validation_parser.add_argument("--root", default=".", help="Workspace root path")
    validation_parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Write the validation dry-run summary to this JSON path",
    )
    validation_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    verification_parser = subcommands.add_parser(
        "verification",
        aliases=["/verification", "verify-status", "/verify-status"],
        help="Show the latest local verification summary",
    )
    verification_parser.add_argument("--root", default=".", help="Workspace root path")

    package_check_parser = subcommands.add_parser(
        "package-check",
        aliases=["/package-check", "packaging", "/packaging"],
        help="Check local packaging metadata before validation run",
    )
    package_check_parser.add_argument("--root", default=".", help="Workspace root path")
    package_check_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

    plugins_parser = subcommands.add_parser(
        "plugins",
        aliases=["/plugins"],
        help="Inspect and operate plugin manifests without executing plugin code",
    )
    plugins_parser.add_argument("--root", default=".", help="Workspace root path")
    plugins_parser.add_argument(
        "plugin_action",
        nargs="?",
        choices=["list", "doctor", "enable", "disable"],
        default="list",
        help="Plugin manifest action",
    )
    plugins_parser.add_argument("--plugin-id", default=None, help="Plugin id to operate on")
    plugins_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )

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
    research_parser.add_argument(
        "--type",
        dest="research_type",
        default="general",
        choices=[
            "general",
            "product_research",
            "architecture_research",
            "implementation_research",
            "competitive_research",
            "paper_research",
            "open_source_research",
            "risk_research",
            "design_pattern_research",
        ],
        help="Research synthesis type",
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
        aliases=["/run", "goal", "/goal"],
        help="Plan, execute, repair, review, and report",
        epilog=SLASH_ALIAS_HELP,
    )
    run_parser.add_argument("goal", nargs="?", help="Natural-language goal")
    run_parser.add_argument("--root", default=".", help="Workspace root path")
    add_workspace_selection_arguments(run_parser)
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
        help="Allow run to execute readonly and disjoint write-scope tasks concurrently",
    )
    run_parser.add_argument(
        "--permission-level",
        choices=["ask", "balanced", "auto", "ask_everything", "reviewed_auto"],
        default="balanced",
        help=PERMISSION_LEVEL_HELP,
    )
    run_parser.add_argument(
        "--model-strategy",
        choices=["auto", "quality", "economy", "local"],
        default="auto",
        help=MODEL_STRATEGY_HELP,
    )
    run_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    accept_parser = subcommands.add_parser(
        "accept",
        aliases=["/accept"],
        help="Accept reviewed results, promote candidates, and finalize the run",
        epilog=f"{ACCEPT_VS_ACCEPTANCE_HELP} {SLASH_ALIAS_HELP}",
    )
    accept_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(accept_parser, "Session id to accept; defaults to current session")
    accept_parser.add_argument(
        "--skip-review",
        action="store_true",
        help="Use the latest eval report instead of running review first",
    )
    accept_parser.add_argument(
        "--no-promote",
        action="store_true",
        help="Do not approve pending candidate promotions automatically",
    )
    accept_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    resume_parser = subcommands.add_parser(
        "resume",
        aliases=["/resume"],
        help="Resume a paused run after decisions",
        epilog=SLASH_ALIAS_HELP,
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
        help="Allow resume to execute readonly and disjoint write-scope tasks concurrently",
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

    promotions_parser = subcommands.add_parser(
        "promotions",
        aliases=["/promotions", "candidates", "/candidates"],
        help="Inspect and operate candidate promotion queue entries",
    )
    promotions_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(
        promotions_parser,
        "Session id whose candidate promotion queue should be used; defaults to current session",
    )
    promotions_parser.add_argument(
        "promotion_action",
        nargs="?",
        choices=["list", "approve", "reject", "retry", "discard"],
        default="list",
        help="Promotion queue action",
    )
    promotions_parser.add_argument(
        "--promotion-id", default=None, help="Promotion id to operate on"
    )
    promotions_parser.add_argument(
        "--status",
        default=None,
        help="Filter list output by status",
    )
    promotions_parser.add_argument(
        "--all-pending",
        action="store_true",
        help="Approve every pending or retryable promotion in the queue",
    )
    promotions_parser.add_argument(
        "--reason",
        default=None,
        help="Reason for reject or discard actions",
    )
    promotions_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
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
        epilog=SLASH_ALIAS_HELP,
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
        epilog=f"{ACCEPT_VS_ACCEPTANCE_HELP} {MAINTAINER_COMMAND_HELP} {SLASH_ALIAS_HELP}",
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
        help="Directory for scenario workspaces; defaults to .asteria/acceptance/workspaces/<run>",
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
        "--run-attempts", type=int, default=1, help="Run attempts per scenario"
    )
    acceptance_parser.add_argument(
        "--model-max-retries",
        type=int,
        default=1,
        help="Model retry attempts inside smoke scenarios",
    )
    acceptance_parser.add_argument(
        "--scenario-timeout-seconds",
        type=int,
        default=600,
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
        epilog=f"{MAINTAINER_COMMAND_HELP} {SLASH_ALIAS_HELP}",
    )
    acceptance_gate_parser.add_argument("--root", default=".", help="Workspace root path")
    acceptance_gate_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Acceptance report path; defaults to .asteria/acceptance/acceptance_report.json",
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
    evidence_bundle_parser = subcommands.add_parser(
        "evidence-bundle",
        aliases=["/evidence-bundle", "diagnostic-bundle", "/diagnostic-bundle"],
        help="Export a redacted post-run evidence bundle for dogfooding analysis",
    )
    evidence_bundle_parser.add_argument("--root", default=".", help="Workspace root path")
    evidence_bundle_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output zip path; defaults to .asteria/evidence_bundles/evidence-<timestamp>.zip",
    )
    evidence_bundle_parser.add_argument(
        "--max-runs",
        type=int,
        default=12,
        help="Maximum recent run directories to include",
    )
    evidence_bundle_parser.add_argument("--json", action="store_true", help="Print JSON")
    evidence_bundle_parser.add_argument(
        "--no-events",
        action="store_true",
        help="Skip events.jsonl tails from run evidence",
    )
    evidence_bundle_parser.add_argument(
        "--no-model-calls",
        action="store_true",
        help="Skip model_calls.jsonl tails from run evidence",
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
    weekly_report_parser.add_argument("--json", action="store_true", help="Print JSON")
    ops_signal_parser = subcommands.add_parser(
        "ops-signal",
        aliases=["/ops-signal", "usage-signal", "/usage-signal"],
        help="Record or summarize background usage signals for maintainer diagnostics",
    )
    ops_signal_parser.add_argument("--root", default=".", help="Workspace root path")
    ops_signal_parser.add_argument("--run-id", default=None, help="Related run id")
    ops_signal_parser.add_argument("--task-kind", default="unknown")
    ops_signal_parser.add_argument("--expected-outcome-category", default="unknown")
    ops_signal_parser.add_argument(
        "--artifact-outcome",
        default="unknown",
        choices=["accepted", "rejected", "blocked", "partial", "unknown"],
    )
    ops_signal_parser.add_argument("--blocker-category", default="none")
    ops_signal_parser.add_argument("--trust-risk", default="none")
    ops_signal_parser.add_argument("--note", "--signal-summary", dest="signal_summary", default="")
    ops_signal_parser.add_argument(
        "--evidence-ref",
        action="append",
        default=[],
        help="Redacted evidence reference such as a run id or evidence-bundle path",
    )
    ops_signal_parser.add_argument(
        "--source",
        default="maintainer_cli",
        help="Signal source, e.g. maintainer_cli or diagnostic_bundle",
    )
    ops_signal_parser.add_argument(
        "--summary",
        "--summary-only",
        "--summary-report",
        dest="ops_summary_only",
        action="store_true",
        help="Only print the aggregate summary without recording a signal",
    )
    ops_signal_parser.add_argument(
        "--analyze",
        action="store_true",
        help="Write usage signal analysis with priority items and candidate decisions",
    )
    ops_signal_parser.add_argument("--json", action="store_true", help="Print JSON")
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
    roadmap_parser.add_argument("--json", action="store_true", help="Print JSON")
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
    daily_report_parser.add_argument(
        "--date", default=None, help="Legacy report date, default today"
    )
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
    studio_benchmark_parser = subcommands.add_parser(
        "studio-benchmark",
        aliases=["/studio-benchmark", "ux-benchmark", "/ux-benchmark"],
        help="Evaluate Studio sessions against user-side agent workspace benchmarks",
    )
    studio_benchmark_parser.add_argument("--root", default=".", help="Workspace root path")
    studio_benchmark_parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Benchmark manifest path; defaults to benchmarks/studio_user_tasks.json",
    )
    studio_benchmark_parser.add_argument(
        "--session-id",
        default=None,
        help="Evaluate only one Studio session id",
    )
    studio_benchmark_parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.set_command_groups(
        [
            (
                "Start",
                "Product workflow commands for ordinary goal -> progress -> review journeys.",
                [
                    ("goal", "Long-task objective mode; keeps working within permissions."),
                    ("plan", "Read-only comprehensive plan; analyze without changing work."),
                    ("status", "Show user-level progress, blockers, and next actions."),
                    ("review", "Inspect result quality before accepting candidate outputs."),
                    ("accept", "Accept reviewed results and finalize the run."),
                    ("debug", "Repair failed execution evidence."),
                ],
            ),
            (
                "Support",
                "Setup and recovery commands used when a workflow asks for them.",
                [
                    ("init", "Initialize a local-first Asteria workspace."),
                    ("resume", "Continue after approvals, pauses, or repair checkpoints."),
                    ("chat", "Lightweight Q&A mode for everyday questions."),
                    ("sessions", "List, inspect, or select session contexts."),
                    ("doctor", "Diagnose local runtime setup and model route health."),
                ],
            ),
            (
                "Maintainer / Inspector",
                "Raw runtime controls and evidence surfaces for experts, validation, and CI.",
                [
                    ("run", "Compatibility alias for goal mode."),
                    ("execute", "Run ready task graph work directly."),
                    ("replan", "Create follow-up tasks from blockers."),
                    ("compact", "Create context snapshots."),
                    ("handoff", "Write recovery handoff context."),
                    ("promotions", "Inspect and operate candidate promotions."),
                    ("plugins", "Inspect plugin manifest policy state."),
                    ("decide", "Create or resolve DecisionPoints."),
                    ("research", "Collect research context."),
                    ("brainstorm", "Generate early solution options."),
                    ("gate", "Run staged validation checks; use --stage release before release."),
                    ("validation", "Plan controlled real-provider validation tasks."),
                    ("evidence-bundle", "Export a redacted diagnostic bundle."),
                    ("ops-signal", "Record background usage signals for ops diagnostics."),
                    ("acceptance", "Run reproducible runtime acceptance scenarios."),
                    ("acceptance-gate", "Evaluate acceptance reports as release gates."),
                    ("acceptance-history", "Show acceptance trend history."),
                    ("capability-report", "Summarize capability and failure trends."),
                    ("weekly-report", "Summarize long-run and release risks."),
                    ("roadmap-update", "Update roadmap artifacts from runtime evidence."),
                    ("daily-plan", "Plan a bounded long-run cycle."),
                    ("daily-run", "Run or stage a bounded long-run cycle."),
                    ("daily-report", "Report on a bounded long-run cycle."),
                    ("verification", "Show latest verification summary."),
                    ("package-check", "Check packaging metadata and docs."),
                    ("gate-status", "Show release validation evidence."),
                    ("version", "Show runtime version diagnostics."),
                    ("studio-benchmark", "Evaluate Studio sessions against UX benchmarks."),
                    ("model-check", "Validate provider configuration."),
                    ("real-model-smoke", "Run an isolated real-model smoke test."),
                    ("real-model-gate", "Run controlled real-model preflight gate."),
                    ("real-model-acceptance", "Run validation/core real-provider suites."),
                    ("validation-run", "Run or dry-run controlled validation tasks."),
                ],
            ),
        ]
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command.lstrip("/")

    if command == "version":
        version_result = VersionCommand().run()
        if args.json:
            print(json.dumps(version_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(version_result.to_text())
        return

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
        if args.json:
            print(json.dumps(model_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(model_result.to_text())
        return

    if command == "plan":
        plan_result = PlanCommand(
            root=Path(args.root),
            goal=args.goal,
            permission_level=args.permission_level,
            model_strategy=args.model_strategy,
            input_roots=[Path(item) for item in args.input_root] if args.input_root else None,
            output_root=Path(args.output_root) if args.output_root else None,
            artifact_root=Path(args.artifact_root) if args.artifact_root else None,
            worktree_policy=args.worktree_policy,
        ).run()
        print(plan_result.to_text())
        print("")
        print("Mode: plan (read-only analysis; no execution started).")
        print(f"Permission level: {args.permission_level}")
        print(f"Model strategy: {args.model_strategy}")
        print('Next: run `asteria goal "<goal>"` when you want Asteria to execute.')
        return

    if command == "chat":
        chat_result = ChatCommand(
            root=Path(args.root),
            question=args.question,
            permission_level=args.permission_level,
            model_strategy=args.model_strategy,
        ).run()
        if args.json:
            print(json.dumps(chat_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(chat_result.to_text())
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

    if command == "status":
        status_result = StatusCommand(root=Path(args.root)).run()
        if args.json:
            print(json.dumps(status_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(status_result.to_text(debug=args.debug))
        return

    if command == "doctor":
        doctor_result = DoctorCommand(root=Path(args.root)).run()
        if args.json:
            print(json.dumps(doctor_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(doctor_result.to_text())
        if not doctor_result.ok:
            raise SystemExit(1)
        return

    if command == "gate-status":
        gate_status_result = GateStatusCommand(root=Path(args.root)).run()
        if args.json:
            print(json.dumps(gate_status_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(gate_status_result.to_text())
        return

    if command == "gate":
        gate_result = GateCommand(
            root=Path(args.root),
            stage=args.stage.replace("-", "_"),
            report_path=getattr(args, "report", None),
            suite=getattr(args, "suite", "core"),
            skip_lint=getattr(args, "skip_lint", False),
            skip_typecheck=getattr(args, "skip_typecheck", False),
            skip_tests=getattr(args, "skip_tests", False),
            skip_acceptance_gate=getattr(args, "skip_acceptance_gate", False),
        ).run()
        if args.json:
            print(json.dumps(gate_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(gate_result.to_text())
        if gate_result.status == "blocked":
            raise SystemExit(1)
        return

    if command == "real-model-smoke":
        run_real_model_smoke(args)
        return

    if command == "real-model-gate":
        run_real_model_gate(args)
        return

    if command == "real-model-acceptance":
        run_real_model_acceptance(args)
        return

    if command == "validation-run":
        validation_run_result = ValidationRunCommand(
            root=Path(args.root),
            goal=args.goal,
            dry_run=args.dry_run,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
            summary_json=args.summary_json,
            probe_ids=args.probe_id,
        ).run()
        if args.json:
            print(json.dumps(validation_run_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(validation_run_result.to_text())
        if validation_run_result.status in {"blocked", "failed"}:
            raise SystemExit(1)
        return

    if command == "validation":
        validation_result = ValidationCommand(
            root=Path(args.root),
            goal=args.goal,
            summary_json=args.summary_json,
        ).run()
        if args.json:
            print(json.dumps(validation_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(validation_result.to_text())
        if validation_result.status == "blocked":
            raise SystemExit(1)
        return

    if command in {"verification", "verify-status"}:
        verification_result = VerificationStatusCommand(root=Path(args.root)).run()
        print(verification_result.to_text())
        return

    if command in {"package-check", "packaging"}:
        package_result = PackageCheckCommand(root=Path(args.root)).run()
        if args.json:
            print(json.dumps(package_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(package_result.to_text())
        if not package_result.ok:
            raise SystemExit(1)
        return

    if command == "plugins":
        plugins_command = PluginsCommand(
            root=Path(args.root),
            action=args.plugin_action,
            plugin_id=args.plugin_id,
        )
        plugins_result = plugins_command.run()
        if args.json:
            print(plugins_command.to_json(plugins_result))
        else:
            print(plugins_result.to_text())
        if args.plugin_action == "doctor" and not plugins_result.ok:
            raise SystemExit(1)
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
            research_type=args.research_type,
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

    if command in {"run", "goal"}:
        run_result = RunCommand(
            root=Path(args.root),
            goal=args.goal,
            run_id=args.session_id,
            max_iterations=args.max_iterations,
            max_tasks_per_iteration=args.max_tasks_per_iteration,
            enable_research=not args.no_research,
            parallel_writes=args.parallel_disjoint_writes,
            mode="goal",
            permission_level=args.permission_level,
            model_strategy=args.model_strategy,
            input_roots=[Path(item) for item in args.input_root] if args.input_root else None,
            output_root=Path(args.output_root) if args.output_root else None,
            artifact_root=Path(args.artifact_root) if args.artifact_root else None,
            worktree_policy=args.worktree_policy,
        ).run()
        if args.json:
            print(json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2))
        else:
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

    if command in {"promotions", "candidates"}:
        promotions_command = PromotionsCommand(
            root=Path(args.root),
            run_id=args.session_id,
            action=args.promotion_action,
            promotion_id=args.promotion_id,
            status=args.status,
            all_pending=args.all_pending,
            reason=args.reason,
        )
        promotions_result = promotions_command.run()
        if args.json:
            print(promotions_command.to_json(promotions_result))
        else:
            print(promotions_result.to_text())
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

    if command == "accept":
        accept_result = AcceptCommand(
            root=Path(args.root),
            run_id=args.session_id,
            skip_review=args.skip_review,
            promote_all=not args.no_promote,
        ).run()
        if args.json:
            print(json.dumps(accept_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(accept_result.to_text())
        if not accept_result.accepted:
            raise SystemExit(1)
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

    if command in {"evidence-bundle", "diagnostic-bundle"}:
        evidence_bundle_result = EvidenceBundleCommand(
            root=Path(args.root),
            output=args.output,
            include_events=not args.no_events,
            include_model_calls=not args.no_model_calls,
            max_runs=args.max_runs,
        ).run()
        if args.json:
            print(json.dumps(evidence_bundle_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(evidence_bundle_result.to_text())
        if not evidence_bundle_result.ok:
            raise SystemExit(1)
        return

    if command in {"weekly-report", "production-report"}:
        weekly_report_result = WeeklyReportCommand(
            root=Path(args.root),
            week_id=args.week_id,
            limit=args.limit,
        ).run()
        if args.json:
            print(json.dumps(weekly_report_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(weekly_report_result.to_text())
        return

    if command in {"ops-signal", "usage-signal"}:
        ops_signal_result = OpsSignalCommand(
            root=Path(args.root),
            run_id=args.run_id,
            task_kind=args.task_kind,
            expected_outcome_category=args.expected_outcome_category,
            artifact_outcome=args.artifact_outcome,
            blocker_category=args.blocker_category,
            trust_risk=args.trust_risk,
            summary=args.signal_summary,
            evidence_refs=args.evidence_ref,
            source=args.source,
            summarize_only=args.ops_summary_only,
            analyze=args.analyze,
        ).run()
        if args.json:
            print(json.dumps(ops_signal_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(ops_signal_result.to_text())
        return

    if command in {"roadmap-update", "prd-update"}:
        roadmap_result = RoadmapCommand(
            root=Path(args.root),
            output=args.output,
        ).run()
        if args.json:
            print(json.dumps(roadmap_result.to_dict(), ensure_ascii=False, indent=2))
        else:
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

    if command in {"studio-benchmark", "ux-benchmark"}:
        studio_benchmark_result = StudioBenchmarkCommand(
            root=Path(args.root),
            manifest=args.manifest,
            session_id=args.session_id,
        ).run()
        if args.json:
            print(json.dumps(studio_benchmark_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(studio_benchmark_result.to_text())
        if not studio_benchmark_result.ok:
            raise SystemExit(1)
        return

    parser.error(f"Unsupported command: {args.command}")
