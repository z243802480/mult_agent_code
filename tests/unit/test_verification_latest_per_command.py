"""P1 ring-recovery benchmark 抓到的收敛 bug 的回归测:完成契约按命令最新结果判校验。

真栈 ring_recovery benchmark(2026-07-14)发现:修复场景里模型必然先跑失败的测试(红)再修再
重跑(绿),旧逻辑把那次初始红计入 verification_total → verification_passed != verification_total
→ "verification did not pass" → 把真修好的活误判 blocked,击穿 repair 环。修:按校验命令去重取
最新结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from asteria_runtime.commands.execute_command import _latest_verification_per_command
from asteria_runtime.core.task_contract import check_completion_contract


@dataclass
class _Obs:
    tool_name: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)


def _cmd(command: str, ok: bool) -> _Obs:
    return _Obs(tool_name="run_command", ok=ok, data={"requested_command": command})


def test_same_command_red_then_green_keeps_latest_green() -> None:
    # The money case: pytest fails, gets fixed, pytest passes → latest is green, one passing result.
    results = _latest_verification_per_command(
        [_cmd("pytest tests", ok=False), _cmd("pytest tests", ok=True)]
    )
    assert len(results) == 1
    assert results[0].ok is True


def test_same_command_green_then_red_keeps_latest_red() -> None:
    # Symmetric: a regression (green then red) is judged red — no silent hiding of a fresh failure.
    results = _latest_verification_per_command(
        [_cmd("pytest tests", ok=True), _cmd("pytest tests", ok=False)]
    )
    assert len(results) == 1
    assert results[0].ok is False


def test_failing_test_not_masked_by_a_different_passing_command() -> None:
    # Anti-gaming (ring_val_f guard): a red pytest cannot be masked by later running an unrelated
    # passing command — each distinct command keeps its own latest, so the red pytest is still red.
    results = _latest_verification_per_command(
        [_cmd("pytest tests", ok=False), _cmd("echo ok", ok=True)]
    )
    oks = {r.data["requested_command"]: r.ok for r in results}
    assert oks == {"pytest tests": False, "echo ok": True}


def test_commandless_observations_pass_through() -> None:
    # Doc/readback verification observations have no command → kept unchanged (not deduped away).
    readback = _Obs(tool_name="read_file", ok=True, data={})
    results = _latest_verification_per_command([readback, readback])
    assert len(results) == 2


def test_repair_loop_now_completes_end_to_end() -> None:
    # End-to-end through the real contract: a bug_fix task whose test failed then passed on the same
    # command is CONTRACT-SATISFIED after dedup (was blocked before the fix).
    task = {"task_kind": "implementation", "expected_changed_files": ["buggy_math.py"]}
    deduped = _latest_verification_per_command(
        [_cmd("pytest tests", ok=False), _cmd("pytest tests", ok=True)]
    )
    check = check_completion_contract(task, ["buggy_math.py"], deduped)
    assert check.ok is True
    assert "verification did not pass" not in check.violations
