"""S16 maintainer dogfood — Beta task 2 doc_update via CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


GOAL = "更新 README 或 CHANGELOG，说明 Asteria Beta 的 Goal→Review→Accept 主路径。"
MAX_DEBUG = 3


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run Beta doc_update dogfood path.")
    parser.add_argument("--workspace", type=Path, default=Path("h:/beta_dogfood_doc_s16"))
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--fresh", action="store_true", help="Remove workspace before init")
    args = parser.parse_args()

    repo = args.repo.resolve()
    workspace = args.workspace.resolve()
    if args.fresh and workspace.exists():
        shutil.rmtree(workspace)

    friction = {"decide": 0, "resume": 0, "debug": 0}
    started = time.time()

    _run([sys.executable, "-m", "asteria_runtime", "init", "--root", str(workspace)], repo)
    _run(
        [
            sys.executable,
            "-m",
            "asteria_runtime",
            "goal",
            GOAL,
            "--root",
            str(workspace),
            "--no-research",
        ],
        repo,
    )

    for _ in range(48):
        status = _status(workspace, repo)
        if status.get("can_accept") or status.get("workflow_state") == "ready_for_accept":
            break
        pending = _pending_decisions(workspace)
        rec = _normalize(status.get("recommended_next_command"))
        if pending:
            _resolve_all(workspace, repo, pending, status)
            friction["decide"] += 1
            friction["resume"] += 1
            time.sleep(3)
            continue
        action = _resolve_action(rec)
        if action == "resume":
            _run([sys.executable, "-m", "asteria_runtime", "resume", "--root", str(workspace)], repo)
            friction["resume"] += 1
            time.sleep(5)
            continue
        if action == "debug":
            if friction["debug"] >= MAX_DEBUG:
                raise SystemExit(f"doc_update exceeded debug limit ({MAX_DEBUG}) at {rec}")
            _run([sys.executable, "-m", "asteria_runtime", "debug", "--root", str(workspace)], repo)
            friction["debug"] += 1
            time.sleep(5)
            continue
        if action == "review":
            _run([sys.executable, "-m", "asteria_runtime", "review", "--root", str(workspace)], repo)
            time.sleep(3)
            continue
        time.sleep(3)
    else:
        raise SystemExit("doc_update did not reach ready_for_accept")

    _run([sys.executable, "-m", "asteria_runtime", "accept", "--root", str(workspace)], repo)
    final = _status(workspace, repo)
    readme = workspace / "README.md"
    report = {
        "ok": final.get("current_phase") == "ACCEPTED",
        "workspace": str(workspace),
        "elapsed_s": round(time.time() - started),
        "friction": friction,
        "readme_exists": readme.is_file(),
        "readme_has_beta_path": "accept" in readme.read_text(encoding="utf-8").lower() if readme.is_file() else False,
        "phase": final.get("current_phase"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


def _pick_option(decision: dict) -> str:
    metadata = decision.get("metadata") or {}
    kind = str(metadata.get("kind") or "")
    if kind == "execution_policy_approval":
        options = decision.get("options") or []
        if any(option.get("option_id") == "approve_once" for option in options):
            return "approve_once"
        if any(option.get("option_id") == "approve_similar_for_session" for option in options):
            return "approve_similar_for_session"
    if kind == "runtime_request" or metadata.get("request_types"):
        return "review_contract"
    if kind == "replan_decision" or metadata.get("reason") == "repair_limit":
        options = decision.get("options") or []
        if any(option.get("option_id") == "create_repair_task" for option in options):
            return "create_repair_task"
    options = decision.get("options") or []
    if any(option.get("option_id") == "review_contract" for option in options):
        return "review_contract"
    return str(decision.get("recommended_option_id") or decision.get("default_option_id") or options[0].get("option_id"))


def _resolve_all(workspace: Path, repo: Path, pending: list[dict], status: dict) -> None:
    run_id = str(status.get("current_session_id") or _latest_run_id(workspace))
    for decision in pending:
        option_id = _pick_option(decision)
        _run(
            [
                sys.executable,
                "-m",
                "asteria_runtime",
                "decide",
                "--root",
                str(workspace),
                "--session-id",
                run_id,
                "--decision-id",
                decision["decision_id"],
                "--select-option-id",
                option_id,
            ],
            repo,
        )
    _run([sys.executable, "-m", "asteria_runtime", "resume", "--root", str(workspace)], repo)


def _pending_decisions(workspace: Path) -> list[dict]:
    run_id = _latest_run_id(workspace)
    if not run_id:
        return []
    path = workspace / ".asteria" / "runs" / run_id / "decisions.jsonl"
    if not path.is_file():
        return []
    by_id: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("decision_id"):
            by_id[item["decision_id"]] = item
    return [item for item in by_id.values() if item.get("status") == "pending"]


def _latest_run_id(workspace: Path) -> str:
    runs_dir = workspace / ".asteria" / "runs"
    if not runs_dir.is_dir():
        return ""
    runs = sorted(path.name for path in runs_dir.iterdir() if path.is_dir() and path.name.startswith("run-"))
    return runs[-1] if runs else ""


def _resolve_action(rec: str) -> str | None:
    if not rec or rec.startswith("accept"):
        return None
    if rec.startswith("decide"):
        return None
    if "debug" in rec:
        return "debug"
    if rec.startswith("resume") or rec.startswith("continue") or rec.startswith("run"):
        return "resume"
    if rec.startswith("review"):
        return "review"
    if rec.startswith("replan"):
        return "resume"
    return None


def _status(workspace: Path, repo: Path) -> dict:
    out = subprocess.check_output(
        [sys.executable, "-m", "asteria_runtime", "status", "--root", str(workspace), "--json"],
        cwd=repo,
        env=_env(repo),
        text=True,
    )
    return json.loads(out)


def _normalize(raw: object) -> str:
    return str(raw or "").replace("asteria ", "").strip().lower()


def _env(repo: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    return env


def _run(cmd: list[str], repo: Path) -> None:
    completed = subprocess.run(cmd, cwd=repo, env=_env(repo), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
