"""Validate Beta task pack docs and maintainer dogfood entry points (Track P)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Check Beta task pack wiring.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--with-doc-dogfood",
        action="store_true",
        help="Run s16 doc_update dogfood (requires real model routes)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    checks: list[dict[str, object]] = []

    tasks_path = root / "benchmarks" / "beta_user_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    task_ids = [task["id"] for task in tasks.get("tasks") or []]
    checks.append(_check("beta_user_tasks.json", tasks_path.is_file() and len(task_ids) >= 3, task_ids))

    onboarding = (root / "docs" / "zh" / "Beta用户入门.md").read_text(encoding="utf-8")
    checklist = (root / "docs" / "zh" / "Beta试跑清单.md").read_text(encoding="utf-8")
    checks.append(_check("onboarding mentions Goal", "Goal" in onboarding and "Review" in onboarding, None))
    checks.append(_check("checklist section D spot-check", "D1" in checklist and "Side chat" in checklist, None))
    checks.append(_check("checklist mentions doc_update", "doc_update" in checklist or "任务 2" in checklist, None))

    for rel in (
        "scripts/s16_doc_update_dogfood.py",
        "scripts/s15_wheel_install_smoke.py",
        "scripts/beta_friction_aggregate.py",
    ):
        path = root / rel
        checks.append(_check(rel, path.is_file(), str(path)))

    ok = all(bool(item["ok"]) for item in checks)
    if args.with_doc_dogfood:
        dogfood = subprocess.run(
            [sys.executable, "scripts/s16_doc_update_dogfood.py", "--repo", str(root), "--fresh"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        checks.append(
            {
                "label": "s16_doc_update_dogfood",
                "ok": dogfood.returncode == 0,
                "detail": dogfood.stdout[-800:] if dogfood.stdout else dogfood.stderr[-400:],
            }
        )
        ok = ok and dogfood.returncode == 0

    report = {
        "ok": ok,
        "purpose": "Beta task pack pulse (Track P)",
        "task_ids": task_ids,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


def _check(label: str, ok: bool, detail: object) -> dict[str, object]:
    return {"label": label, "ok": ok, "detail": detail}


if __name__ == "__main__":
    main()
