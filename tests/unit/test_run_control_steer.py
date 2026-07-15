"""中途 steer(ADR-0029 ①):把用户在运行中说的话,在回合边界作为 user-turn 上下文注入。

关键性质(每条对应一个真会咬人的失败):
- 只在**回合边界**注入 —— 运行中写进来的 steer 在**下一个**回合起点才出现,绝不 mid-tool-batch。
- 注入的是**用户原话**(role="user"),harness 不解析、不合成 next_action —— 模型自己决定怎么采纳。
- **读并清**:每条指令只注入一次,否则每个回合都重放,模型被同一句话反复打断。
- 未注入回调(flag 关)时循环逐字节不变。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.model_driven_turn import ToolObservation, run_model_driven_turn
from asteria_runtime.core.run_control import request_steer, take_steer


def test_signal_round_trip_appends_drains_in_order_and_clears(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    assert take_steer(run_dir) == []  # nothing queued

    request_steer(run_dir, "先跑 lint")
    request_steer(run_dir, "  再改用 pytest  ")  # trimmed
    request_steer(run_dir, "")  # empty is a no-op

    drained = take_steer(run_dir)
    assert drained == ["先跑 lint", "再改用 pytest"]  # order preserved, empty dropped
    # Read-and-clear: a second take gets nothing, so the loop can't replay the same instruction.
    assert take_steer(run_dir) == []


class _CapturingClient:
    """Records the messages of every request so we can assert what the model actually saw. Returns a
    tool call for the first two turns (so the loop keeps going), then finishes."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def chat(self, request: Any) -> Any:  # noqa: ANN401
        self.requests.append(request)
        if len(self.requests) < 3:
            content = (
                '{"narration": "干活中", "tool_calls": '
                '[{"tool_name": "write_file", "args": {"path": "a.txt", "content": "x"}}], '
                '"done": false}'
            )
        else:
            content = '{"narration": "做完了", "tool_calls": [], "done": true}'
        return type("Resp", (), {"content": content, "raw": {}})()


class _SteeringToolRunner:
    """On the FIRST tool batch, the user steers mid-run (writes steer.request). It must NOT appear in
    the turn that is already in flight, only at the next boundary."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.batches = 0

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: Any,  # noqa: ANN401
        stop_on_failure: bool = False,
    ) -> list[ToolObservation]:
        self.batches += 1
        if self.batches == 1:
            request_steer(self.run_dir, "改用 pytest 重跑测试")
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


def _user_texts(request: Any) -> list[str]:
    return [m.content for m in request.messages if getattr(m, "role", None) == "user"]


def test_mid_run_steer_lands_at_next_boundary_exactly_once(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    client = _CapturingClient()
    runner = _SteeringToolRunner(run_dir)

    result = run_model_driven_turn(
        model_client=client,  # type: ignore[arg-type]
        tool_runner=runner,  # type: ignore[arg-type]
        task={"task_id": "task-0001", "title": "t"},
        context=None,
        available_tools=["write_file"],
        system_prompt="s",
        user_prompt="u",
        max_iterations=5,
        take_steer=lambda: take_steer(run_dir),
    )

    steer = "改用 pytest 重跑测试"

    def steer_count(request: Any) -> int:
        return sum(1 for text in _user_texts(request) if text == steer)

    # Turn 1 was already in flight when the user steered → its request must NOT contain the steer.
    assert steer_count(client.requests[0]) == 0
    # Turn 2's boundary picked it up and injected it as a user message — exactly once.
    assert steer_count(client.requests[1]) == 1
    # Read-and-clear: the message stays in conversation history (as any user turn would), but it is
    # never RE-injected — turn 3 still shows it exactly once, not twice. A missing read-and-clear
    # would replay it every turn, so this count is the real regression guard.
    assert steer_count(client.requests[2]) == 1
    # Exactly one steer event was emitted, carrying the user's verbatim words.
    steer_events = [e for e in result.events if e.kind == "steer"]
    assert len(steer_events) == 1
    assert steer_events[0].text == steer


def test_no_steer_callback_is_byte_identical(tmp_path: Path) -> None:
    client = _CapturingClient()
    runner = _SteeringToolRunner(tmp_path)
    result = run_model_driven_turn(
        model_client=client,  # type: ignore[arg-type]
        tool_runner=runner,  # type: ignore[arg-type]
        task={"task_id": "task-0001", "title": "t"},
        context=None,
        available_tools=["write_file"],
        system_prompt="s",
        user_prompt="u",
        max_iterations=5,
        take_steer=None,  # flag off → no steer read at all
    )
    # No steer events, and the run completed normally on the model's own "done".
    assert not [e for e in result.events if e.kind == "steer"]
    assert result.status == "completed"
