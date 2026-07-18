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

from asteria_runtime.core.model_driven_turn import (
    TurnControl,
    TurnEvent,
    run_model_driven_turn,
)


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


def _json_resp(narration: str, tool_calls=None, done: bool = False) -> SimpleNamespace:
    """构造 JSON transport 的响应替身：content 是 {narration, tool_calls, done} 的 JSON 串。"""
    payload = {"narration": narration, "tool_calls": tool_calls or [], "done": done}
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), raw_response={})


def _run(model, tools, *, task=None, transport="tool_use", **kw):
    return run_model_driven_turn(
        model_client=model,
        tool_runner=tools,
        task=task or {"task_id": "task-0001", "allowed_tools": ["write_file", "run_tests"]},
        context=object(),
        available_tools=["write_file", "read_file", "run_command", "run_tests"],
        system_prompt="system",
        user_prompt="build calc.py",
        transport=transport,
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


# --- JSON transport（本 glm/minimax 弱模型栈的已证明通路）---------------------------------


def test_json_transport_executes_tools_and_completes() -> None:
    model = FakeModelClient(
        [
            _json_resp("建 calc.py", [{"tool_name": "write_file", "args": {"path": "calc.py", "content": "code"}}]),
            _json_resp("完成", [], done=True),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote calc.py")]])

    result = _run(model, tools, transport="json")

    assert result.status == "completed"
    assert result.iterations == 2
    assert result.final_message == "完成"
    assert len(result.observations) == 1 and result.observations[0].tool_name == "write_file"
    # 第一次请求必须注入 JSON 契约 + 走 response_format=json（不发 tools）。
    first = model.requests[0]
    assert "OUTPUT CONTRACT" in first.messages[0].content
    assert first.response_format == "json" and first.tools is None


def test_json_transport_failure_fed_back_without_repair_branch() -> None:
    model = FakeModelClient(
        [
            _json_resp("跑测试", [{"tool_name": "run_tests", "args": {"command": "pytest"}}]),
            _json_resp("测试挂了,我来修", [{"tool_name": "write_file", "args": {"path": "calc.py", "content": "fix"}}]),
            _json_resp("修好了", [], done=True),
        ]
    )
    tools = FakeToolRunner(
        [
            [FakeToolResult(ok=False, summary="1 failed", status="failure", error="AssertionError")],
            [FakeToolResult(ok=True, summary="wrote calc.py")],
        ]
    )

    result = _run(model, tools, transport="json")

    assert result.status == "completed" and result.iterations == 3
    assert len(result.observations) == 2 and result.observations[0].ok is False
    second_call_texts = [m.content for m in model.requests[1].messages]
    assert any("1 failed" in t or "AssertionError" in t for t in second_call_texts)


def test_json_transport_done_flag_completes_even_with_tool_calls() -> None:
    # done=true 收尾优先——即便模型顺手又塞了 tool_calls,也当完成,防止困惑的模型无限调用。
    model = FakeModelClient(
        [_json_resp("其实已经好了", [{"tool_name": "write_file", "args": {"path": "x", "content": "y"}}], done=True)]
    )
    tools = FakeToolRunner([])
    task = {"task_id": "task-0001", "allowed_tools": ["write_file"]}

    result = _run(model, tools, transport="json", task=task)

    assert result.status == "completed"
    assert result.iterations == 1
    assert result.observations == []


def test_json_transport_invalid_json_does_not_crash() -> None:
    model = FakeModelClient([SimpleNamespace(content="这不是 JSON", raw_response={})])
    tools = FakeToolRunner([])
    task = {"task_id": "task-0001", "allowed_tools": []}  # 无待办 -> 不轻推,如实完成

    result = _run(model, tools, transport="json", task=task)

    assert result.status == "completed"
    assert result.iterations == 1
    assert result.observations == []


# --- 控制型 Hook 胶水（把方法论层串进循环，保连续性）--------------------------------------


def test_hook_turn_start_injects_reminder() -> None:
    model = FakeModelClient(
        [
            _json_resp("建文件", [{"tool_name": "write_file", "args": {"path": "x", "content": "y"}}]),
            _json_resp("完成", [], done=True),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote")]])

    def hook(name: str, _payload: dict) -> TurnControl:
        if name == "turn_start":
            return TurnControl(additional_context="REMINDER: verify before finishing")
        return TurnControl()

    result = _run(model, tools, transport="json", hook=hook)

    assert result.status == "completed"
    # The reminder was injected into the model's first turn as input.
    first_call_texts = [m.content for m in model.requests[0].messages]
    assert any("REMINDER" in text for text in first_call_texts)


def test_hook_pre_final_holds_loop_open_until_evidence() -> None:
    # Model tries to stop at iteration 1; the stop-guardrail hook forces one more turn (continuity),
    # then the model does the work and finishes. Guardrail = boundary, model still decides the step.
    model = FakeModelClient(
        [
            _json_resp("看起来不用做什么"),  # premature stop
            _json_resp("好,建文件", [{"tool_name": "write_file", "args": {"path": "calc.py", "content": "code"}}]),
            _json_resp("完成", [], done=True),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote calc.py")]])
    fired = {"n": 0}

    def hook(name: str, _payload: dict) -> TurnControl:
        if name == "pre_final" and fired["n"] == 0:
            fired["n"] += 1
            return TurnControl(additional_context="artifact not produced yet, continue", continue_turn=True)
        return TurnControl()

    task = {"task_id": "task-0001", "allowed_tools": ["write_file"], "write_scope": ["calc.py"]}
    result = _run(model, tools, transport="json", task=task, hook=hook)

    assert result.status == "completed"
    assert result.iterations == 3
    assert len(result.observations) == 1
    second_call_texts = [m.content for m in model.requests[1].messages]
    assert any("continue" in text for text in second_call_texts)


# --- 人审边界（ADR-0016：人审=显式边界，不是模型认知）----------------------------------------


def test_approval_gate_halts_whole_batch_and_reports_paused() -> None:
    # gate 对这批工具返回一个待人批决策 = 命中人审边界：整批**一个都不跑**（无残留写入），
    # 循环返回 paused 并携带该决策上抛。模型这一步的 tool_calls 被原地停住，不进 observation。
    model = FakeModelClient(
        [
            _json_resp(
                "先跑一条需人批的命令,再写文件",
                [
                    {"tool_name": "run_command", "args": {"command": "rm -rf / && echo hi"}},
                    {"tool_name": "write_file", "args": {"path": "calc.py", "content": "code"}},
                ],
            ),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True)]])
    decision = {"decision_id": "decision-0001", "metadata": {"kind": "execution_policy_approval"}}

    def gate(calls: list[dict]):
        # 只要这批里有需人批的动作,就返回决策(真值)——整批停手。
        return decision if calls else None

    result = _run(model, tools, transport="json", approval_gate=gate)

    assert result.status == "paused"
    assert result.pending_decision is decision
    assert result.iterations == 1
    # 关键:整批未执行——工具网关一次都没被调用,没有任何 observation 残留。
    assert tools.calls_seen == []
    assert result.observations == []
    assert result.events[-1].kind == "paused"


def test_approval_gate_none_lets_batch_run_as_usual() -> None:
    # gate 对该批返回 None（已在案/无需人批）= 未命中边界：整批照常执行，行为与无 gate 时一致。
    model = FakeModelClient(
        [
            _json_resp("建文件", [{"tool_name": "write_file", "args": {"path": "calc.py", "content": "code"}}]),
            _json_resp("完成", [], done=True),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(ok=True, summary="wrote calc.py")]])
    seen_batches: list[list[dict]] = []

    def gate(calls: list[dict]):
        seen_batches.append(calls)
        return None

    result = _run(model, tools, transport="json", approval_gate=gate)

    assert result.status == "completed"
    assert result.iterations == 2
    assert len(result.observations) == 1 and result.observations[0].tool_name == "write_file"
    # gate 被问过一次(那一批工具),但放行了。
    assert len(seen_batches) == 1


def test_history_microcompact_collapses_old_observation_payloads() -> None:
    # 累积历史微压缩（S90 刀一）：payload 单条早有 6KB 上限（agent_harness._clip），但"总和"
    # 此前无界——旧 observation 的大输出会原封不动躺满整段循环。超预算时必须坍缩**最旧**的
    # observation 消息（换成带"如何再生"提示的摘要），最近 keep_recent 条保留全文，
    # assistant 决策轨迹一字不动。
    big = "X" * 4_000
    model = FakeModelClient(
        [
            _json_resp("step1", [{"tool_name": "run_command", "args": {"command": "echo 1"}}]),
            _json_resp("step2", [{"tool_name": "run_command", "args": {"command": "echo 2"}}]),
            _json_resp("step3", [{"tool_name": "run_command", "args": {"command": "echo 3"}}]),
            _json_resp("done", done=True),
        ]
    )
    tools = FakeToolRunner(
        [
            [FakeToolResult(summary="ran echo 1", data={"stdout": big + "-one"})],
            [FakeToolResult(summary="ran echo 2", data={"stdout": big + "-two"})],
            [FakeToolResult(summary="ran echo 3", data={"stdout": big + "-three"})],
        ]
    )

    result = _run(
        model,
        tools,
        transport="json",
        history_char_budget=9_000,
        keep_recent_observation_payloads=1,
    )

    assert result.status == "completed"
    final_messages = [str(m.content) for m in model.requests[-1].messages]
    observation_messages = [t for t in final_messages if t.startswith("Tool results")]
    assert len(observation_messages) == 3
    # 最旧的 observation 被坍缩：payload 没了、带"再生"提示；summary 仍在。
    assert "-one" not in observation_messages[0]
    assert "elided" in observation_messages[0]
    assert "ran echo 1" in observation_messages[0]
    # 最近一条保留全文 payload。
    assert "-three" in observation_messages[-1]
    # assistant 决策轨迹不被触碰（三条 assistant JSON 都在）。
    assistant_texts = [t for t in final_messages if '"tool_calls"' in t and t.startswith("{")]
    assert len(assistant_texts) == 3


def test_history_microcompact_noop_when_within_budget() -> None:
    model = FakeModelClient(
        [
            _json_resp("step1", [{"tool_name": "run_command", "args": {"command": "echo 1"}}]),
            _json_resp("done", done=True),
        ]
    )
    tools = FakeToolRunner([[FakeToolResult(summary="ran", data={"stdout": "tiny"})]])

    result = _run(model, tools, transport="json")

    assert result.status == "completed"
    final_messages = [str(m.content) for m in model.requests[-1].messages]
    observation_messages = [t for t in final_messages if t.startswith("Tool results")]
    assert "tiny" in observation_messages[0]
    assert "elided" not in observation_messages[0]
