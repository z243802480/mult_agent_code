"""用户暂停:协作式停手信号 + 回合边界。

关键性质(每条都对应一个真会咬人的失败):
- 暂停只在**回合起点**生效 —— 绝不把一批工具劈成两半(否则 workspace 留残迹、run 不可 resume)。
- 暂停 ≠ 待人批决策 —— pending_decision 必须是 None,否则上层会当成权限门去生成 DecisionPoint。
- 信号必须能被消费 —— 留着它,resume 会在第一个回合边界立刻又暂停,run 永远起不来。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.model_driven_turn import ToolObservation, run_model_driven_turn
from asteria_runtime.core.run_control import (
    clear_pause,
    pause_reason,
    pause_requested,
    request_pause,
)


class _RecordingClient:
    """每轮都要求再调一次工具,永不收尾——只有暂停/保险丝能让循环停下。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: Any) -> Any:  # noqa: ANN401
        self.calls += 1
        return type(
            "Resp",
            (),
            {
                "content": '{"narration": "干活中", "tool_calls": '
                '[{"tool_name": "write_file", "args": {"path": "a.txt", "content": "x"}}], '
                '"done": false}',
                "raw": {},
            },
        )()


class _RecordingToolRunner:
    def __init__(self) -> None:
        self.batches = 0

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: Any,  # noqa: ANN401
        stop_on_failure: bool = False,
    ) -> list[ToolObservation]:
        self.batches += 1
        return [
            ToolObservation(
                tool_name=call.get("tool_name", "write_file"),
                ok=True,
                status="success",
                summary="ok",
                data={},
                artifact_refs=[],
            )
            for call in calls
        ]


def _turn(pause_flag: dict[str, bool], max_iterations: int = 4):
    client = _RecordingClient()
    runner = _RecordingToolRunner()
    result = run_model_driven_turn(
        model_client=client,  # type: ignore[arg-type]
        tool_runner=runner,  # type: ignore[arg-type]
        task={"task_id": "task-0001", "title": "t"},
        context=None,
        available_tools=["write_file"],
        system_prompt="s",
        user_prompt="u",
        max_iterations=max_iterations,
        pause_requested=lambda: pause_flag["paused"],
    )
    return result, client, runner


def test_pause_before_the_first_turn_runs_nothing_at_all() -> None:
    result, client, runner = _turn({"paused": True})
    assert result.status == "paused"
    # 一次模型调用都没发、一批工具都没跑 —— 暂停必须是干净的。
    assert client.calls == 0
    assert runner.batches == 0
    assert result.iterations == 0
    # 用户暂停不是待人批决策;混淆会让上层去生成一个 DecisionPoint。
    assert result.pending_decision is None


def test_pause_takes_effect_at_a_turn_boundary_not_mid_batch() -> None:
    flag = {"paused": False}
    client = _RecordingClient()
    runner = _RecordingToolRunner()

    # 第一批工具跑完之后才按下暂停。
    original = runner.run_tool_calls

    def run_then_pause(
        calls: list[dict],
        task: dict,
        context: Any,  # noqa: ANN401
        stop_on_failure: bool = False,
    ) -> list[ToolObservation]:
        observations = original(calls, task, context, stop_on_failure)
        flag["paused"] = True
        return observations

    runner.run_tool_calls = run_then_pause  # type: ignore[method-assign]

    result = run_model_driven_turn(
        model_client=client,  # type: ignore[arg-type]
        tool_runner=runner,  # type: ignore[arg-type]
        task={"task_id": "task-0001", "title": "t"},
        context=None,
        available_tools=["write_file"],
        system_prompt="s",
        user_prompt="u",
        max_iterations=5,
        pause_requested=lambda: flag["paused"],
    )
    assert result.status == "paused"
    # 第一轮**完整跑完**(工具批没被腰斩),第二轮起点才停手。
    assert runner.batches == 1
    assert client.calls == 1
    assert result.iterations == 1
    assert len(result.observations) == 1
    assert any(event.kind == "paused" for event in result.events)


def test_no_pause_signal_leaves_the_loop_alone() -> None:
    result, client, runner = _turn({"paused": False}, max_iterations=3)
    # 没按暂停 → 循环照常跑到保险丝。
    assert result.status == "budget_exhausted"
    assert runner.batches == 3


def test_signal_round_trip_and_consumption(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    assert pause_requested(run_dir) is False

    request_pause(run_dir, reason="用户在 Studio 点了暂停")
    assert pause_requested(run_dir) is True
    assert pause_reason(run_dir) == "用户在 Studio 点了暂停"

    # 消费信号。不清掉的话,resume 会在第一个回合边界立刻又暂停 —— run 永远起不来。
    clear_pause(run_dir)
    assert pause_requested(run_dir) is False

    # 重复清除必须无害(进程被杀 / 并发 resume)。
    clear_pause(run_dir)
    assert pause_requested(run_dir) is False


def test_request_pause_is_idempotent(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    request_pause(run_dir)
    request_pause(run_dir, reason="再点一次")
    assert pause_requested(run_dir) is True
    assert pause_reason(run_dir) == "再点一次"
