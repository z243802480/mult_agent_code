"""ring_recovery benchmark 断言逻辑的确定性单测(喂合成 run_dir·无真模型)。

证据契约(见 benchmarks/reference_briefs/B-ring-recovery-realstack-benchmark.md):PASS 需
基线红+终绿+loop completed+真 provider;三态诚实 PASS/NO-RECOVER/NO-REAL-PROVIDER。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ring_recovery_smoke import evaluate_ring_recovery


def _seed_run_dir(
    run_dir: Path,
    *,
    status: str,
    exit_reason: str,
    verif: list[tuple[str, str]],
    providers: list[str],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "agent_loop_run_summary.json").write_text(
        json.dumps({"status": status, "exit_reason": exit_reason, "rounds_completed": 3}),
        encoding="utf-8",
    )
    (run_dir / "tool_calls.jsonl").write_text(
        "\n".join(
            json.dumps({"tool_name": name, "status": st}) for name, st in verif
        ),
        encoding="utf-8",
    )
    (run_dir / "model_calls.jsonl").write_text(
        "\n".join(json.dumps({"model_provider": p}) for p in providers),
        encoding="utf-8",
    )


def test_pass_when_recovered_on_real_provider(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    _seed_run_dir(
        run_dir,
        status="completed",
        exit_reason="completed",
        verif=[("run_command", "failure"), ("run_command", "success")],
        providers=["fake", "zai"],
    )
    report = evaluate_ring_recovery(
        run_dir, baseline_red=True, final_green=True, allow_fake=False
    )
    assert report["verdict"] == "PASS"
    assert report["red_then_green_in_loop"] is True
    assert report["used_real_provider"] is True


def test_no_recover_when_baseline_stays_red(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r2"
    _seed_run_dir(
        run_dir,
        status="blocked",
        exit_reason="tool_failed",
        verif=[("run_command", "failure")],
        providers=["zai"],
    )
    report = evaluate_ring_recovery(
        run_dir, baseline_red=True, final_green=False, allow_fake=False
    )
    assert report["verdict"] == "NO-RECOVER"


def test_no_recover_when_loop_not_completed_even_if_green(tmp_path: Path) -> None:
    # Guards the exact bug the benchmark caught: code fixed (final green) but loop mis-reports blocked.
    run_dir = tmp_path / "runs" / "r3"
    _seed_run_dir(
        run_dir,
        status="blocked",
        exit_reason="tool_failed",
        verif=[("run_command", "failure"), ("run_command", "success")],
        providers=["zai"],
    )
    report = evaluate_ring_recovery(
        run_dir, baseline_red=True, final_green=True, allow_fake=False
    )
    assert report["verdict"] == "NO-RECOVER"
    assert report["loop_completed"] is False


def test_no_real_provider_when_only_fake(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r4"
    _seed_run_dir(
        run_dir,
        status="completed",
        exit_reason="completed",
        verif=[("run_command", "success")],
        providers=["fake"],
    )
    report = evaluate_ring_recovery(
        run_dir, baseline_red=True, final_green=True, allow_fake=False
    )
    assert report["verdict"] == "NO-REAL-PROVIDER"


def test_allow_fake_bypasses_real_provider_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r5"
    _seed_run_dir(
        run_dir,
        status="completed",
        exit_reason="completed",
        verif=[("run_command", "success")],
        providers=["fake"],
    )
    report = evaluate_ring_recovery(
        run_dir, baseline_red=True, final_green=True, allow_fake=True
    )
    assert report["verdict"] == "PASS"
