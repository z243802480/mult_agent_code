"""Beta trial maintainer smoke — maps to docs/zh/Beta试跑清单.md automated checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run Beta trial maintainer smoke checks.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--with-b6",
        action="store_true",
        help="Include B6 restricted user sim (requires real model routes)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    checklist = root / "docs" / "zh" / "Beta试跑清单.md"
    steps: list[dict[str, object]] = []

    steps.append(_run_pytest(root, "tests/unit/test_documentation_contracts.py"))
    steps.append(_run_pytest(root, "tests/unit/test_workspaces_command.py"))
    steps.append(_run_node(root, "studio/scripts/workspace-switcher-smoke.mjs"))
    steps.append(_run_node(root, "studio/scripts/git-changes-smoke.mjs"))
    steps.append(_run_python(root, "scripts/phase8_maintainer_smoke.py", ["--root", str(root)]))

    if args.with_b6:
        steps.append(_run_node(root, "studio/scripts/b6-restricted-user-sim.mjs"))

    ok = all(step.get("ok") for step in steps)
    report = {
        "ok": ok,
        "purpose": "Beta trial maintainer smoke (workspace switcher + git changes + Phase 8 pulse).",
        "checklist_doc": str(checklist.relative_to(root)).replace("\\", "/"),
        "manual_sections": ["A install", "B execute", "C review/accept"],
        "automated_sections": ["A4 workspace API", "A5 studio launch path", "git status/diff", "doc contracts"],
        "steps": steps,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _run_pytest(root: Path, target: str) -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", target, "-q"]
    return _run(root, " ".join(cmd), cmd)


def _run_python(root: Path, script: str, extra: list[str]) -> dict[str, object]:
    cmd = [sys.executable, script, *extra]
    return _run(root, " ".join(cmd), cmd)


def _run_node(root: Path, script: str) -> dict[str, object]:
    cmd = ["node", script]
    return _run(root, " ".join(cmd), cmd)


def _run(root: Path, label: str, cmd: list[str]) -> dict[str, object]:
    completed = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "step": label,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-800:],
    }


if __name__ == "__main__":
    main()
