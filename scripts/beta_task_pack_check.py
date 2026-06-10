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
    checks.append(_check("static_landing_page task", "static_landing_page" in task_ids, None))
    checks.append(_check("install_doc", (root / "docs/zh/Beta-GitHub-Release安装.md").is_file(), None))
    checks.append(_check("build_beta_release.py", (root / "scripts/build_beta_release.py").is_file(), None))
    checks.append(_check("beta_install.ps1", (root / "scripts/beta_install.ps1").is_file(), None))

    onboarding = (root / "docs" / "zh" / "Beta用户入门.md").read_text(encoding="utf-8")
    checklist = (root / "docs" / "zh" / "Beta试跑清单.md").read_text(encoding="utf-8")
    invitation = (root / "docs" / "zh" / "Beta内测邀请.md").read_text(encoding="utf-8")
    trial_template = (
        root / "docs" / "zh" / "reports" / "S14-beta-user-trial-template.md"
    ).read_text(encoding="utf-8")
    checks.append(_check("onboarding mentions studio path", "asteria studio" in onboarding.lower() and "accept" in onboarding.lower(), None))
    checks.append(_check("checklist section D spot-check", "D1" in checklist and "Side chat" in checklist, None))
    checks.append(_check("checklist mentions doc_update", "doc_update" in checklist or "任务 2" in checklist or "第二次试跑" in checklist, None))
    checks.append(_check("checklist release install", "install.ps1" in checklist or "asteria-beta" in checklist, None))
    checks.append(
        _check(
            "trial template captures session experience",
            all(
                field in trial_template
                for field in (
                    "首次看到有效动作耗时",
                    "最长一次无反馈等待",
                    "是否理解下一步",
                    "Inspector 是否帮助确认系统真的做了事",
                )
            ),
            None,
        )
    )
    checks.append(
        _check(
            "trial template enforces external evidence boundary",
            "至少 3 名明确非维护者" in trial_template
            and "单个试跑不能直接打开产品 Slice" in trial_template,
            None,
        )
    )
    checks.append(
        _check(
            "maintainer invitation has release preflight",
            all(
                command in invitation
                for command in (
                    "beta_task_pack_check.py",
                    "beta_trial_smoke.py",
                    "build_beta_release.py",
                )
            ),
            None,
        )
    )

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
