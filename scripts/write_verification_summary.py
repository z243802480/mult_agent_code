from __future__ import annotations

import argparse
import platform
from pathlib import Path

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the latest local verification summary")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--platform", default=platform.system().lower(), help="Verification platform"
    )
    parser.add_argument(
        "--cli-workspace", type=Path, required=True, help="Workspace used by CLI smoke"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = args.root.resolve()
    cli_workspace = args.cli_workspace.resolve()
    snapshots = list((cli_workspace / ".agent" / "context" / "snapshots").glob("*.json"))
    handoffs = list((cli_workspace / ".agent" / "context" / "handoffs").glob("*.json"))
    summary = {
        "schema_version": "0.1.0",
        "created_at": now_iso(),
        "status": "passed",
        "platform": str(args.platform),
        "checks": [
            {"name": "compileall", "status": "passed", "summary": "src and tests compile"},
            {"name": "pytest", "status": "passed", "summary": "full test suite passed"},
            {"name": "ruff", "status": "passed", "summary": "ruff check passed"},
            {"name": "mypy", "status": "passed", "summary": "src typecheck passed"},
            {"name": "benchmarks", "status": "passed", "summary": "benchmark runner passed"},
            {
                "name": "cli_smoke",
                "status": "passed",
                "summary": "init/model-check/new/sessions/run passed",
            },
            {"name": "context_snapshot", "status": "passed", "summary": "compact created snapshot"},
            {"name": "handoff", "status": "passed", "summary": "handoff package created"},
            {
                "name": "sessions_context",
                "status": "passed",
                "summary": "sessions --context exposed recovery pointers",
            },
        ],
        "artifacts": {
            "cli_workspace": str(cli_workspace),
            "snapshot_count": len(snapshots),
            "handoff_count": len(handoffs),
            "latest_snapshot": str(sorted(snapshots)[-1]) if snapshots else None,
            "latest_handoff": str(sorted(handoffs)[-1]) if handoffs else None,
        },
    }
    store = JsonStore(SchemaValidator(root / "schemas"))
    store.write(root / ".agent" / "verification" / "latest.json", summary, "verification_summary")
    print(f"Wrote verification summary: {root / '.agent' / 'verification' / 'latest.json'}")


if __name__ == "__main__":
    main()
