from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_runtime.commands.acceptance_history_command import AcceptanceHistoryCommand


def append_history(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def history_entry(
    suite: str,
    *,
    created_at: str,
    ok: bool = True,
    failed: int = 0,
    model_calls: int = 3,
    delta_model_calls: int = 0,
    delta_duration: float = -2.0,
    delta_repairs: int = 0,
    delta_compactions: int = 0,
) -> dict:
    return {
        "ok": ok,
        "suite": suite,
        "created_at": created_at,
        "aggregate": {
            "total": 1,
            "passed": 0 if failed else 1,
            "failed": failed,
            "duration_seconds": 10.0,
            "model_calls": model_calls,
            "tool_calls": 2,
            "estimated_input_tokens": 100,
            "estimated_output_tokens": 20,
            "repair_attempts": 0,
            "failed_scenarios": ["file_smoke"] if failed else [],
        },
        "trend": {
            "previous": {"created_at": "2026-05-05T10:00:00+08:00"},
            "deltas": {
                "failed": failed,
                "duration_seconds": delta_duration,
                "model_calls": delta_model_calls,
                "tool_calls": 0,
                "estimated_input_tokens": -10,
                "estimated_output_tokens": 5,
                "repair_attempts": delta_repairs,
                "context_compactions": delta_compactions,
            },
        },
    }


def test_acceptance_history_reports_missing_history(tmp_path: Path) -> None:
    result = AcceptanceHistoryCommand(tmp_path).run()

    assert result.entries == []
    assert "Acceptance history: none" in result.to_text()


def test_acceptance_history_filters_by_suite_and_limit(tmp_path: Path) -> None:
    path = tmp_path / ".agent" / "acceptance" / "history.jsonl"
    append_history(path, history_entry("smoke", created_at="2026-05-06T10:00:00+08:00"))
    append_history(path, history_entry("core", created_at="2026-05-06T11:00:00+08:00"))
    append_history(
        path,
        history_entry(
            "core",
            created_at="2026-05-06T12:00:00+08:00",
            ok=False,
            failed=1,
            model_calls=5,
            delta_model_calls=2,
        ),
    )

    result = AcceptanceHistoryCommand(tmp_path, suite="core", limit=1).run()
    text = result.to_text()

    assert len(result.entries) == 1
    assert "Acceptance history" in text
    assert "core [fail]" in text
    assert "model=5" in text
    assert "delta: failed=+1" in text
    assert "model_calls=+2" in text
    assert "failed scenarios: file_smoke" in text


def test_acceptance_history_warns_on_regressions(tmp_path: Path) -> None:
    path = tmp_path / ".agent" / "acceptance" / "history.jsonl"
    append_history(path, history_entry("smoke", created_at="2026-05-06T10:00:00+08:00"))
    append_history(
        path,
        history_entry(
            "smoke",
            created_at="2026-05-06T11:00:00+08:00",
            ok=False,
            failed=1,
            delta_model_calls=6,
            delta_duration=121.0,
            delta_repairs=1,
            delta_compactions=1,
        ),
    )

    result = AcceptanceHistoryCommand(tmp_path).run()
    text = result.to_text()

    assert len(result.warnings) == 6
    assert "Warnings:" in text
    assert "latest run has 1 failed scenario" in text
    assert "model calls increased by 6" in text
    assert "duration increased by 121s" in text


def test_acceptance_history_fail_on_warning_exits_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    append_history(
        path,
        history_entry(
            "smoke",
            created_at="2026-05-06T11:00:00+08:00",
            ok=False,
            failed=1,
        ),
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_runtime",
            "/acceptance-history",
            "--root",
            str(tmp_path),
            "--history-jsonl",
            str(path),
            "--fail-on-warning",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Warnings:" in completed.stdout
