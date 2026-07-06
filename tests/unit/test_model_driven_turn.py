"""立真身单轮循环的形态证明（ADR-0016 §1）。

用假模型 + 假工具网关，隔离验证 `run_model_driven_turn` 的核心语义，不依赖真实 provider /
gateway（它们各有自己的测试）。证明四条：
1. 模型停止调用工具 = 本轮完成（唯一控制分支）。
2. 工具失败被当 observation 回灌，模型据此自我修复——**没有独立 repair 状态机分支**。
3. `max_iterations` 保险丝把不收尾的循环停在 budget_exhausted（可 resume，不冒充完成/失败）。
4. 弱模型第一轮"过早收尾"被轻推一次而非当完成；无待办工作时则如实立即完成。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from asteria_runtime.core.model_driven_turn import TurnEvent, run_model_driven_turn


def _resp(narration: str, *tool_calls: tuple[str, dict]) -> SimpleNamespace:
    """构造一个最小的 ChatResponse 替身：content=narration，raw_response=OpenAI 风格工具调用。"""
    if tool_calls:
        message = {
            "content": narration,
            "tool_calls": [
                {"function": {"name": name, "arguments": json.dumps(args)}}
                for name, args in tool_calls
            ],
        }
    else:
        message = {"content": narration}
    return SimpleNamespace(content=narration, raw_response={"choices": [{"message": message}]})


class FakeModelClient:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.requests: list = []

    def chat(self, request):
        self.requests.append(request)
        assert self._responses, "model was called more times than scripted"
        return self._responses.pop(0)


@dataclass
class FakeToolResult:
    ok: bool = True
    summary: str = "ok"
    status: str = "success"
    error: str | None = None
    data: dict = field(default_factory=dict)


class FakeToolRunner:
    """按调用次序返回预设结果批次；stop_on_failure 被忽略（失败作为结果返回，不抛）。"""

    def __init__(self, batches: list[list[FakeToolResult]]) -> None:
        self._batches = list(batches)
        self.calls_seen: list[list[dict]] = []

    def run_tool_calls(self, calls, task, context, stop_on_failure=True, **_kw):
        self.calls_seen.append(calls)
        if self._batches:
            return self._batches.pop(0)
        return [FakeToolResult() for _ in calls]


def _run(model, tools, *, task=None, **kw):
    return run_model_driven_turn(
        model_client=model,
        tool_runner=tools,
        task=task or {"task_id": "task-0001", "allowed_tools": ["write_file", "run_tests"]},
        context=object(),
        available_tools=["write_file", "read_file", "run_command", "run_tests"],
        system_prompt="system",
        user_prompt="build calc.py",
        **kw,
    )


def test_completes_when_model_stops_calling_tools() -> None:
    model = FakeModelClient(
        [
            _resp("先建 calc.py", ("write_file", {"path": "calc.py", "content": "def add(a,b): return a+b"})),
            _resp("完成了", ),  # 无工具调用 = 模型认为做完
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote calc.py")]])

    result = _run(model, tools)

    assert result.status == "completed"
    assert result.iterations == 2
    assert result.final_message == "完成了"
    assert len(result.observations) == 1
    assert result.observations[0].ok and result.observations[0].tool_name == "write_file"
    # 第二次模型调用必须收到了第一步的工具 observation（结果被回灌）。
    second_call_texts = [m.content for m in model.requests[1].messages]
    assert any("wrote calc.py" in t for t in second_call_texts)


def test_failure_fed_back_as_observation_without_repair_branch() -> None:
    model = FakeModelClient(
        [
            _resp("先跑测试", ("run_tests", {"command": "pytest"})),
            _resp("测试挂了,我来修", ("write_file", {"path": "calc.py", "content": "fixed"})),
            _resp("修好了", ),
        ]
    )
    tools = FakeToolRunner(
        [
            [FakeToolResult(ok=False, summary="1 failed", status="failure", error="AssertionError")],
            [FakeToolResult(ok=True, summary="wrote calc.py")],
        ]
    )

    result = _run(model, tools)

    # 全程没有抛异常、没有进任何 repair 分支——失败只是 observation，模型自己决定下一步。
    assert result.status == "completed"
    assert result.iterations == 3
    assert len(result.observations) == 2
    assert result.observations[0].ok is False and result.observations[0].error == "AssertionError"
    assert result.observations[1].ok is True
    # 失败 observation 必须被喂回给模型的第二次调用。
    second_call_texts = [m.content for m in model.requests[1].messages]
    assert any("1 failed" in t or "AssertionError" in t for t in second_call_texts)


def test_fuse_trips_when_model_never_stops() -> None:
    model = FakeModelClient([_resp(f"第{i}步", ("write_file", {"path": "x", "content": "y"})) for i in range(3)])
    tools = FakeToolRunner([[FakeToolResult()] for _ in range(3)])

    result = _run(model, tools, max_iterations=3)

    assert result.status == "budget_exhausted"
    assert result.iterations == 3
    assert len(result.observations) == 3
    assert result.events[-1].kind == "fuse"


def test_premature_first_round_stop_is_nudged() -> None:
    model = FakeModelClient(
        [
            _resp("看起来不用做什么"),  # 第一轮就无工具调用 = 过早收尾
            _resp("好的,我来建文件", ("write_file", {"path": "calc.py", "content": "code"})),
            _resp("完成"),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote calc.py")]])
    task = {"task_id": "task-0001", "allowed_tools": ["write_file"], "write_scope": ["calc.py"]}

    result = _run(model, tools, task=task)

    # 过早的 stop 没被当完成，而是轻推一次继续，最终真正产出后才收尾。
    assert result.status == "completed"
    assert result.iterations == 3
    assert len(result.observations) == 1
    nudge_texts = [m.content for m in model.requests[1].messages]
    assert any("not complete" in t and "calc.py" in t for t in nudge_texts)


def test_no_pending_work_stops_immediately() -> None:
    model = FakeModelClient([_resp("你好,有什么可以帮你")])
    tools = FakeToolRunner([])
    task = {"task_id": "task-0001", "allowed_tools": []}  # 无 write_scope/expected_artifacts

    result = _run(model, tools, task=task)

    assert result.status == "completed"
    assert result.iterations == 1
    assert result.observations == []


def test_tool_gateway_exception_becomes_observation() -> None:
    class ExplodingRunner:
        def run_tool_calls(self, calls, task, context, stop_on_failure=True, **_kw):
            raise RuntimeError("registry unavailable")

    model = FakeModelClient(
        [
            _resp("跑命令", ("run_command", {"command": "ls"})),
            _resp("好,停"),
        ]
    )

    result = _run(model, ExplodingRunner())

    # 工具层自身炸了也只是 observation，不向上抛、不触发独立 repair。
    assert result.status == "completed"
    assert result.iterations == 2
    assert len(result.observations) == 1
    assert result.observations[0].ok is False
    assert "registry unavailable" in (result.observations[0].error or "")


def test_events_are_emitted_in_order() -> None:
    seen: list[TurnEvent] = []
    model = FakeModelClient(
        [
            _resp("建文件", ("write_file", {"path": "calc.py", "content": "code"})),
            _resp("done"),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote")]])

    _run(model, tools, on_event=seen.append)

    kinds = [event.kind for event in seen]
    assert kinds == ["narration", "tool_observation", "narration", "final"]
