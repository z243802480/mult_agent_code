from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from asteria_runtime import __version__
from asteria_runtime.commands.background_run_command import BackgroundRunCommand
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
from asteria_runtime.commands.supervised_goal_loop_command import SupervisedGoalLoopCommand
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
from asteria_runtime.commands.validation_run_command import ValidationRunCommand
from asteria_runtime.commands.handoff_command import HandoffCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.mcp_command import McpCommand
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
from asteria_runtime.commands.studio_command import StudioCommand
from asteria_runtime.commands.workspaces_command import WorkspacesCommand, resolve_studio_launch_root
from asteria_runtime.commands.verification_command import VerificationStatusCommand
from asteria_runtime.commands.correctness_eval_command import CorrectnessEvalCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.commands.weekly_report_command import WeeklyReportCommand
from asteria_runtime.models.route_diagnostics import silently_canned_tiers
from asteria_runtime.models.routing import MODEL_TIERS
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
    "economy favors cheaper models. local is currently a routing-preference placeholder "
    "(no dedicated local route is wired; it falls back to the configured default tier until "
    "a local provider route is configured)."
)
MODEL_NAME_HELP = (
    "Pin the model a tier asks for, as TIER=MODEL_NAME (repeatable; tiers: strong, medium, cheap). "
    "Keeps that tier's configured provider, base URL and API key — only the model name changes, so "
    "this cannot point a tier at a provider whose credentials you have not configured. Example: "
    "--model-name strong=glm-4.6. Omitted tiers keep whatever their route resolves to."
)
def model_name_override(value: str) -> tuple[str, str]:
    """Parse one ``TIER=MODEL`` pair. An argparse ``type``, so bad input is a clean usage error.

    Rejects here rather than dropping: a pin the user typed on the command line and misspelled must
    say so, not run with the wrong model. (run_config.json takes the opposite line — it is
    hand-editable and a typo there must not stop a run; see normalize_model_name_overrides.)
    """
    tier, separator, name = str(value).partition("=")
    tier = tier.strip().lower()
    name = name.strip()
    if not separator or not name:
        raise argparse.ArgumentTypeError(f"expected TIER=MODEL (e.g. strong=glm-4.6), got {value!r}")
    if tier not in MODEL_TIERS:
        raise argparse.ArgumentTypeError(
            f"unknown model tier {tier!r}; expected one of: {', '.join(MODEL_TIERS)}"
        )
    return tier, name


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

    def error(self, message: str) -> None:  # type: ignore[override]
        # For the top-level `asteria` parser, replace argparse's usage wall + raw error (which dumps
        # ~40 subcommands and their /slash aliases) with a short line that points at the curated help.
        if self.prog == "asteria" and self._command_groups:
            hint = message.split(" (choose from")[0] if "invalid choice" in message else message
            sys.stderr.write(f"asteria: {hint}\nRun `asteria --help` to see available commands.\n")
            raise SystemExit(2)
        super().error(message)

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
        help=(
            "Regenerate managed metadata (project.json/policies.json/root_snapshot.json/backlog.json), "
            "overwriting existing files. Without --force, re-init preserves them; AGENTS.md is never overwritten."
        ),
    )
    init_parser.add_argument(
        "--north-star-title",
        default=None,
        help="Optional long-horizon goal title; creates .asteria/north_star.json when set",
    )
    init_parser.add_argument(
        "--north-star-statement",
        default=None,
        help="Optional North Star statement (defaults to --north-star-title)",
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
        aliases=["/chat", "ask", "/ask"],
        help="Lightweight Ask/Q&A mode; no state-changing project work",
    )
    chat_parser.add_argument("question", help="Question or short request")
    chat_parser.add_argument("--root", default=".", help="Workspace root path")
    chat_parser.add_argument(
        "--permission-level",
        choices=["ask", "balanced", "auto", "ask_everything", "reviewed_auto"],
        # Ask/chat is the read-only Q&A surface (no state-changing project work), so it defaults to
        # the read-only `ask` tier — matching `plan` and the documented Ask contract. Users can still
        # opt into balanced/auto explicitly; only the default is read-only.
        default="ask",
        help=PERMISSION_LEVEL_HELP,
    )
    chat_parser.add_argument(
        "--model-strategy",
        choices=["auto", "quality", "economy", "local"],
        default="auto",
        help=MODEL_STRATEGY_HELP,
    )
    chat_parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="PATH",
        dest="images",
        help="Attach an image to the question (repeatable). Requires a configured vision route.",
    )
    chat_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    route_parser = subcommands.add_parser(
        "route",
        aliases=["/route"],
        help="Model-steered orchestration routing for Studio and CLI",
    )
    route_parser.add_argument("message", help="User message to route")
    route_parser.add_argument("--root", default=".", help="Workspace root path")
    route_parser.add_argument(
        "--mode",
        default="auto",
        help="Requested Studio/CLI mode override (auto, chat, plan, run, resume, review, accept)",
    )
    route_parser.add_argument(
        "--permission-level",
        choices=["ask", "balanced", "auto", "ask_everything", "reviewed_auto"],
        default="balanced",
        help=PERMISSION_LEVEL_HELP,
    )
    route_parser.add_argument(
        "--rules-only",
        action="store_true",
        help="Skip model routing and use deterministic fallback rules",
    )
    route_parser.add_argument(
        "--router-mode",
        choices=["model", "rules"],
        default=None,
        help="Override policy studio.orchestration_router (model=strong semantic route)",
    )
    route_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    route_parser.add_argument(
        "--slim",
        action="store_true",
        help="Omit orchestration catalog from JSON output",
    )

    subcommands.add_parser(
        "route-worker",
        aliases=["/route-worker"],
        help="Long-lived JSONL route worker for Studio (stdin/stdout)",
    )

    new_parser = subcommands.add_parser(
        "new",
        aliases=["/new"],
        help="Start a new isolated goal context",
    )
    new_parser.add_argument("goal", help="Natural-language goal")
    new_parser.add_argument("--root", default=".", help="Workspace root path")

    sessions_parser = subcommands.add_parser(
        "sessions",
        aliases=["/sessions"],
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
        epilog=f"{MAINTAINER_COMMAND_HELP} {SLASH_ALIAS_HELP}",
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

    verification_parser = subcommands.add_parser(
        "verification",
        aliases=["/verification"],
        help="Show the latest local verification summary",
    )
    verification_parser.add_argument("--root", default=".", help="Workspace root path")

    # Maintainer/eval command: hidden from the default help (argparse.SUPPRESS), like gate/*.
    correctness_eval_parser = subcommands.add_parser(
        "correctness-eval",
        aliases=["/correctness-eval"],
        help=argparse.SUPPRESS,
    )
    correctness_eval_parser.add_argument("--root", default=".", help="Workspace root path")
    correctness_eval_parser.add_argument(
        "--run-id", dest="run_id", default=None, help="Run/session id; defaults to the latest run"
    )
    correctness_eval_parser.add_argument("--json", action="store_true", help="Emit JSON")
    correctness_eval_parser.add_argument(
        "--rerun",
        action="store_true",
        help="Independently re-execute the recorded verification commands (fresh exit codes)",
    )

    # Maintainer: verify the audit-log hash chain of a run (S77 P1 tamper-evidence). Hidden.
    audit_verify_parser = subcommands.add_parser(
        "audit-verify",
        aliases=["/audit-verify"],
        help=argparse.SUPPRESS,
    )
    audit_verify_parser.add_argument("--root", default=".", help="Workspace root path")
    audit_verify_parser.add_argument(
        "--run-id", dest="run_id", default=None, help="Run/session id; defaults to the latest run"
    )
    audit_verify_parser.add_argument("--json", action="store_true", help="Emit JSON")

    package_check_parser = subcommands.add_parser(
        "package-check",
        aliases=["/package-check"],
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

    mcp_parser = subcommands.add_parser(
        "mcp",
        aliases=["/mcp"],
        help="Inspect the curated MCP server catalog and enable/disable servers (opt-in)",
    )
    mcp_parser.add_argument("--root", default=".", help="Workspace root path")
    mcp_parser.add_argument(
        "mcp_action",
        nargs="?",
        choices=["list", "enable", "disable"],
        default="list",
        help="MCP catalog action (default: list)",
    )
    mcp_parser.add_argument(
        "--name",
        default=None,
        help="Catalog server name to enable/disable (e.g. git, fetch)",
    )
    mcp_parser.add_argument(
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
        "--continue-session",
        action="store_true",
        help="Reuse the current accepted session run: append follow-up work and execute without replanning",
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
    run_parser.add_argument(
        "--model-name",
        action="append",
        type=model_name_override,
        metavar="TIER=MODEL",
        default=[],
        help=MODEL_NAME_HELP,
    )
    run_parser.add_argument(
        "--background",
        action="store_true",
        help="Start the goal in a local background subprocess (durable registry; cloud defer)",
    )
    # North Star supervised multi-slice loop is frozen (master plan); these remain functional
    # for maintainers but are hidden from the default `run`/`goal` help (argparse.SUPPRESS),
    # matching how other maintainer-only surface is kept out of the ordinary user journey.
    run_parser.add_argument(
        "--toward-north-star",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "--max-slices",
        type=int,
        default=3,
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    background_parser = subcommands.add_parser(
        "background",
        help="Local background subprocess runs (durable registry; cloud VM defer)",
    )
    background_parser.add_argument("--root", default=".", help="Workspace root path")
    background_sub = background_parser.add_subparsers(dest="background_action", required=True)
    background_start = background_sub.add_parser("start", help="Start a goal in the background")
    background_start.add_argument("goal", help="Natural-language goal")
    background_start.add_argument(
        "--remote",
        action="store_true",
        help="Record remote/cloud background intent (stub; true VM deferred)",
    )
    background_start.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    background_status = background_sub.add_parser("status", help="Show background run badge status")
    background_status.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    background_list = background_sub.add_parser("list", help="List background runs from registry")
    background_list.add_argument("--json", action="store_true", help="Print machine-readable JSON")

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

    pause_parser = subcommands.add_parser(
        "pause",
        aliases=["/pause"],
        help="Ask a running run to stop at its next turn boundary (resume with `asteria resume`)",
        epilog=SLASH_ALIAS_HELP,
    )
    pause_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(pause_parser, "Session id; defaults to current session")

    steer_parser = subcommands.add_parser(
        "steer",
        aliases=["/steer"],
        help="Hand a running run a new instruction; it picks it up at its next turn boundary and carries on",
        epilog=SLASH_ALIAS_HELP,
    )
    steer_parser.add_argument("instruction", help="What to tell the running run (its own words)")
    steer_parser.add_argument("--root", default=".", help="Workspace root path")
    add_session_id_argument(steer_parser, "Session id; defaults to current session")

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
        aliases=["/promotions"],
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
    review_parser.add_argument(
        "--rerun",
        action="store_true",
        help="Independently re-run recorded verification commands for the correctness signal",
    )

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
    decide_parser.add_argument(
        "--open-question",
        action="store_true",
        help="Create an open-ended question (free-text answer, no fixed options)",
    )
    decide_parser.add_argument(
        "--answer",
        default=None,
        help="Answer an open-ended question with free text",
    )

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
        aliases=["/acceptance-history"],
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
        aliases=["/acceptance-gate"],
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
        aliases=["/capability-report"],
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
        aliases=["/evidence-bundle"],
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
        aliases=["/weekly-report"],
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
        aliases=["/ops-signal"],
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
        aliases=["/roadmap-update"],
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
        aliases=["/daily-plan"],
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
        aliases=["/daily-run"],
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
        aliases=["/daily-report"],
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
        aliases=["/studio-benchmark"],
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
    studio_benchmark_parser.add_argument(
        "--run-id",
        default=None,
        help="Evaluate only one runtime run id for user_progress contract checks",
    )
    studio_benchmark_parser.add_argument("--json", action="store_true", help="Print JSON")
    studio_parser = subcommands.add_parser(
        "studio",
        aliases=["/studio"],
        help="Launch Asteria Studio (API server and UI)",
    )
    studio_parser.add_argument("--root", default=".", help="Workspace root path")
    studio_parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime install root; defaults to --root",
    )
    studio_parser.add_argument("--api-port", type=int, default=8787, help="Studio API port")
    studio_parser.add_argument("--ui-port", type=int, default=5174, help="Studio UI port")
    studio_parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Start API server only (no Vite UI)",
    )
    studio_parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip npm install when node_modules is missing",
    )
    studio_parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser automatically",
    )
    studio_parser.add_argument(
        "--build",
        action="store_true",
        help="Build the UI (npm run build) first, then serve UI + API from one port (no dev server)",
    )
    studio_parser.add_argument("--json", action="store_true", help="Print launch config JSON and exit")
    workspaces_parser = subcommands.add_parser(
        "workspaces",
        help="List or register workspace roots for Studio project switcher",
    )
    workspaces_sub = workspaces_parser.add_subparsers(dest="workspaces_action", required=True)
    workspaces_list = workspaces_sub.add_parser("list", help="List recent and current workspaces")
    workspaces_list.add_argument("--json", action="store_true", help="Print JSON")
    workspaces_register = workspaces_sub.add_parser(
        "register",
        help="Register a workspace root and optionally initialize it",
    )
    workspaces_register.add_argument("--root", required=True, help="Workspace directory path")
    workspaces_register.add_argument(
        "--no-init",
        action="store_true",
        help="Do not run init when .asteria/project.json is missing",
    )
    workspaces_register.add_argument("--json", action="store_true", help="Print JSON")
    workspaces_describe = workspaces_sub.add_parser(
        "describe",
        help="Describe workspace readiness (init, git, AGENTS.md)",
    )
    workspaces_describe.add_argument("--root", required=True, help="Workspace directory path")
    workspaces_describe.add_argument("--json", action="store_true", help="Print JSON")
    parser.set_command_groups(
        [
            (
                "Start",
                "Product workflow commands for ordinary goal -> progress -> review journeys.",
                [
                    ("goal", "Long-task objective mode; keeps working within permissions."),
                    ("plan", "Read-only comprehensive plan; analyze without changing work."),
                    ("ask", "Lightweight Ask/Q&A; mounts session context when needed."),
                    ("status", "Show user-level progress, blockers, and next actions."),
                    ("review", "Inspect result quality before accepting candidate outputs."),
                    ("accept", "Accept reviewed results and finalize the run."),
                    ("debug", "Continue failed work in the current session."),
                ],
            ),
            (
                "Support",
                "Setup and recovery commands used when a workflow asks for them.",
                [
                    ("init", "Initialize a local-first Asteria workspace."),
                    ("workspaces", "List or register workspace roots for Studio."),
                    ("studio", "Launch Asteria Studio (API server and UI)."),
                    ("resume", "Continue after approvals, pauses, or repair checkpoints."),
                    ("sessions", "List, inspect, or select session contexts."),
                    ("doctor", "Diagnose local runtime setup and model route health."),
                    ("model-check", "Verify a configured model provider is reachable."),
                ],
            ),
        ]
    )
    return parser


def _warn_if_model_tiers_canned() -> None:
    """Print a loud, unmissable banner when some model tiers silently return canned output.

    The library layer already emits a ``warnings.warn`` (``factory._warn_if_tier_silently_offline``),
    but Python warnings are easily filtered/deduped and lost mid-run — a zero-config operator running
    ``asteria run`` never notices they are getting fabricated output on a mixed config. Surface it as
    a prominent stderr banner on the interactive run/resume path (goes to stderr, so ``--json`` stdout
    stays clean). Fully-offline (intentional air-gap) and fully-real configs stay silent. Never raises
    — a diagnostics hiccup must not block a run.
    """
    try:
        canned = silently_canned_tiers()
    except Exception:  # noqa: BLE001 — visibility helper must never break a run.
        return
    if not canned:
        return
    tiers = ", ".join(canned)
    # ASCII-only, no box-drawing/emoji: this goes to stderr, which on a Windows GBK console (piped
    # or redirected) uses errors='strict' and would raise UnicodeEncodeError on chars like U+26A0,
    # crashing the very run this is meant to warn about. Wrapped in try/except for the same reason.
    banner = (
        "\n"
        "!! MODEL CONFIG WARNING - some tiers return fake/canned output\n"
        f"   Tier(s) [{tiers}] use the fake/offline provider and return CANNED placeholder\n"
        "   output (not a real model) while real providers are configured for other tiers.\n"
        "   Any step routed to those tiers (summaries, classification, some checks) uses\n"
        "   FABRICATED output - results may look real but are not.\n"
        f"   Fix: set AGENT_MODEL_{canned[0].upper()}_PROVIDER (or AGENT_MODEL_PROVIDER) to a\n"
        "   real provider, or run `asteria doctor` to see the full route table.\n\n"
    )
    try:
        sys.stderr.write(banner)
    except (UnicodeEncodeError, OSError):  # never let a warning banner break the run
        pass


def _format_cli_error(exc: Exception) -> str:
    """Turn an uncaught business exception into a human line + an actionable next step.

    Keeps the raw traceback out of a user's terminal (set ASTERIA_DEBUG=1 to restore it).
    """
    name = exc.__class__.__name__
    message = str(exc).strip() or name
    lines = [f"asteria: {message}"]
    lowered = message.lower()
    if name == "ModelProviderError" or "provider" in lowered or "api key" in lowered or "route" in lowered:
        lines.append(
            "Next: configure a model provider (set AGENT_MODEL_PROVIDER + <PROVIDER>_API_KEY), then"
        )
        lines.append(
            '      run `asteria doctor --root .` to check config, or try offline with '
            '`AGENT_MODEL_PROVIDER=fake asteria goal "..." --root .`.'
        )
    else:
        lines.append(
            "Next: run `asteria status --root .` for the current state, "
            "or `asteria doctor --root .` to check setup."
        )
    lines.append("(set ASTERIA_DEBUG=1 for the full traceback)")
    return "\n".join(lines) + "\n"


def main() -> None:
    """CLI entry point with a top-level guard so users get guidance, not a raw traceback."""
    try:
        _run_cli()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.stderr.write("\nasteria: interrupted.\n")
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001 - deliberate top-level CLI guard
        if os.environ.get("ASTERIA_DEBUG") == "1":
            raise
        sys.stderr.write(_format_cli_error(exc))
        raise SystemExit(1)


def _run_cli() -> None:
    parser = build_parser()
    if len(sys.argv) <= 1:
        # Bare `asteria`: show the curated grouped help, not argparse's required-argument usage wall.
        sys.stdout.write(parser.format_help())
        raise SystemExit(0)
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
            north_star_title=args.north_star_title,
            north_star_statement=args.north_star_statement,
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

    if command in {"chat", "ask"}:
        chat_result = ChatCommand(
            root=Path(args.root),
            question=args.question,
            permission_level=args.permission_level,
            model_strategy=args.model_strategy,
            attachments=[Path(item) for item in getattr(args, "images", []) or []],
        ).run()
        if args.json:
            print(json.dumps(chat_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(chat_result.to_text())
        return

    if command == "route-worker":
        from asteria_runtime.route_worker import run_route_worker

        run_route_worker()
        return

    if command == "route":
        from asteria_runtime.commands.route_command import RouteCommand

        route_result = RouteCommand(
            root=Path(args.root),
            message=args.message,
            requested_mode=args.mode,
            permission_level=args.permission_level,
            use_model=not args.rules_only,
            router_mode_override=args.router_mode,
        ).run()
        if args.json:
            print(
                json.dumps(
                    route_result.to_dict(include_catalog=not args.slim),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(route_result.to_text())
        return

    if command == "new":
        new_result = NewCommand(root=Path(args.root), goal=args.goal).run()
        print(new_result.to_text())
        return

    if command == "sessions":
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

    if command == "verification":
        verification_result = VerificationStatusCommand(root=Path(args.root)).run()
        print(verification_result.to_text())
        return

    if command == "correctness-eval":
        correctness_result = CorrectnessEvalCommand(
            root=Path(args.root), run_id=args.run_id, rerun=bool(getattr(args, "rerun", False))
        ).run()
        if args.json:
            print(json.dumps(correctness_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(correctness_result.to_text())
        return

    if command == "audit-verify":
        from asteria_runtime.storage import audit_chain
        from asteria_runtime.storage.run_store import RunStore
        from asteria_runtime.storage.schema_validator import SchemaValidator

        agent_dir = Path(args.root) / ".asteria"
        # SchemaValidator requires the schema dir. Calling it with no argument raised TypeError, so
        # `asteria audit-verify` crashed on every invocation — mypy flagged it, but nothing ran mypy.
        run_store = RunStore(
            agent_dir, SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
        )
        run_id = args.run_id or run_store.current_session_id()
        if not run_id:
            print("No run found. Run `asteria run \"goal\"` first.")
            raise SystemExit(1)
        audit_result = audit_chain.verify_run(run_store.run_dir(run_id))
        if args.json:
            print(json.dumps(audit_result, ensure_ascii=False, indent=2))
        else:
            status = "OK · 审计链完整" if audit_result["ok"] else "TAMPERED · 审计链被篡改"
            print(f"Audit chain {run_id}: {status} ({audit_result['chained_files']} chained files)")
            for check in audit_result["checks"]:
                if not check["ok"]:
                    print(f"  ✗ {check['file']}: {check.get('reason')}"
                          + (f" @seq {check['break_seq']}" if check.get("break_seq") else ""))
        if not audit_result["ok"]:
            raise SystemExit(1)
        return

    if command == "package-check":
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

    if command == "mcp":
        mcp_command = McpCommand(
            root=Path(args.root),
            action=args.mcp_action,
            name=args.name,
        )
        mcp_result = mcp_command.run()
        if args.json:
            print(mcp_command.to_json(mcp_result))
        else:
            print(mcp_result.to_text())
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
        _warn_if_model_tiers_canned()
        if args.background:
            if not args.goal:
                raise SystemExit("goal is required when using --background")
            bg_result = BackgroundRunCommand(
                root=Path(args.root),
                action="start",
                goal=args.goal,
            ).run()
            if args.json:
                print(json.dumps(bg_result.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(bg_result.to_text())
            return
        if args.toward_north_star:
            loop_result = SupervisedGoalLoopCommand(
                root=Path(args.root),
                max_slices=args.max_slices,
                enable_research=not args.no_research,
                permission_level=args.permission_level,
                model_strategy=args.model_strategy,
            ).run()
            if args.json:
                print(json.dumps(loop_result.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(loop_result.to_text())
            return
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
            model_name_overrides=dict(args.model_name),
            input_roots=[Path(item) for item in args.input_root] if args.input_root else None,
            output_root=Path(args.output_root) if args.output_root else None,
            artifact_root=Path(args.artifact_root) if args.artifact_root else None,
            worktree_policy=args.worktree_policy,
            continue_session=getattr(args, "continue_session", False),
        ).run()
        if args.json:
            print(json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(run_result.to_text())
        return

    if command == "pause":
        from asteria_runtime.core.run_control import request_pause
        from asteria_runtime.storage.run_store import RunStore
        from asteria_runtime.storage.schema_validator import SchemaValidator

        agent_dir = Path(args.root) / ".asteria"
        run_store = RunStore(
            agent_dir, SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
        )
        run_id = args.session_id or run_store.current_session_id()
        if not run_id:
            print("No run found. Run `asteria run \"goal\"` first.")
            raise SystemExit(1)
        request_pause(run_store.run_dir(run_id))
        # 诚实措辞:这是一个**请求**。run 在下一个回合边界(上一批工具跑完之后)才会真的停手——
        # 我们绝不半跑一批工具。如果它已经结束了,信号就只是躺在那儿,由 resume 清掉。
        print(f"Pause requested for {run_id}. It will stop at the next turn boundary.")
        print("Resume with `asteria resume` — completed work is kept.")
        return

    if command == "steer":
        from asteria_runtime.core.run_control import request_steer
        from asteria_runtime.storage.run_store import RunStore
        from asteria_runtime.storage.schema_validator import SchemaValidator

        agent_dir = Path(args.root) / ".asteria"
        run_store = RunStore(
            agent_dir, SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
        )
        run_id = args.session_id or run_store.current_session_id()
        if not run_id:
            print("No run found. Run `asteria run \"goal\"` first.")
            raise SystemExit(1)
        if request_steer(run_store.run_dir(run_id), args.instruction) is None:
            print("Nothing to steer with — the instruction was empty.")
            raise SystemExit(1)
        # 诚实措辞:这是一条给运行中 run 的**补充指令**,在下一个回合边界(上一批工具跑完之后)才会
        # 被带给模型——绝不打断正在跑的一批工具。生效需 `agent_loop.mid_run_steer` 开;关着时信号只是
        # 躺在那儿。是否采纳由模型自己决定(ADR-0016:注入用户原话,认知归模型)。
        print(f"Steer queued for {run_id}. The run will see it at its next turn boundary.")
        return

    if command == "resume":
        _warn_if_model_tiers_canned()
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

    if command == "background":
        bg_result = BackgroundRunCommand(
            root=Path(args.root),
            action=args.background_action,
            goal=getattr(args, "goal", None),
            remote=bool(getattr(args, "remote", False)),
        ).run()
        if getattr(args, "json", False):
            print(json.dumps(bg_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(bg_result.to_text())
        return

    if command == "promotions":
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
        review_result = ReviewCommand(
            root=Path(args.root),
            run_id=args.session_id,
            rerun=bool(getattr(args, "rerun", False)),
        ).run()
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
            answer=args.answer,
            open_question=args.open_question,
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

    if command == "acceptance-history":
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

    if command == "acceptance-gate":
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

    if command == "capability-report":
        capability_report_result = CapabilityReportCommand(
            root=Path(args.root),
            limit=args.limit,
        ).run()
        print(capability_report_result.to_text())
        return

    if command == "evidence-bundle":
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

    if command == "weekly-report":
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

    if command == "ops-signal":
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

    if command == "roadmap-update":
        roadmap_result = RoadmapCommand(
            root=Path(args.root),
            output=args.output,
        ).run()
        if args.json:
            print(json.dumps(roadmap_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(roadmap_result.to_text())
        return

    if command == "daily-plan":
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

    if command == "daily-run":
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

    if command == "daily-report":
        daily_report_result = DailyReportCommand(
            root=Path(args.root),
            date=args.cycle_id or args.date,
            objective=args.objective,
        ).run()
        print(daily_report_result.to_text())
        return

    if command == "studio-benchmark":
        studio_benchmark_result = StudioBenchmarkCommand(
            root=Path(args.root),
            manifest=args.manifest,
            session_id=args.session_id,
            run_id=args.run_id,
        ).run()
        if args.json:
            print(json.dumps(studio_benchmark_result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(studio_benchmark_result.to_text())
        if not studio_benchmark_result.ok:
            raise SystemExit(1)
        return

    if command == "studio":
        launch_root = resolve_studio_launch_root(Path(args.root))
        runtime_root = Path(args.runtime_root) if args.runtime_root else launch_root
        studio_command = StudioCommand(
            root=launch_root,
            runtime_root=runtime_root,
            api_port=args.api_port,
            ui_port=args.ui_port,
            backend_only=args.backend_only,
            skip_install=args.skip_install,
            open_browser=not args.no_open,
            build=args.build,
        )
        if args.json:
            preview = studio_command.preview()
            print(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2))
            return
        launch = studio_command.run()
        print(launch.to_text())
        return

    if command == "workspaces":
        workspaces_command = WorkspacesCommand()
        action = args.workspaces_action
        if action == "list":
            result = workspaces_command.list_registry()
        elif action == "register":
            result = workspaces_command.register(
                Path(args.root),
                init_if_needed=not args.no_init,
            )
        elif action == "describe":
            result = workspaces_command.describe(Path(args.root))
        else:
            parser.error(f"Unsupported workspaces action: {action}")
            return
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(result.to_text())
        if not result.ok:
            raise SystemExit(1)
        return

    parser.error(f"Unsupported command: {args.command}")
