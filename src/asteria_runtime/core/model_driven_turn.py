"""模型驱动的单轮循环（立真身 · ADR-0016 §1 认知归模型）。

这是核心循环的"真身"：一条 `model → tool → observation → model` 单循环，形态对齐
codex-rs `tasks/regular.rs::run_turn` 与 Anthropic tool-use 规范循环——

- **唯一控制分支**：模型这一步吐 tool call 就执行、否则（只说话不调工具）视为本轮完成。
  没有闭合的 `next_action` 枚举，没有 harness 替模型算的"该 repair / 该 replan / 算不算做完"。
- **错误即 observation**：工具/命令失败被格式化成 observation 回灌给模型，由模型自己决定下一步；
  **没有独立的 repair 状态机分支**（对比 `execute_command` 的 `if next_action_kind=="repair"`）。
- **边界归 harness**：`max_iterations` 是可 resume 的保险丝（预算边界，不是认知），工具执行的
  权限/沙箱/写作用域由注入的 `tool_runner`（`ToolExecutionGateway`）在调用边界强制。

本模块**只装配已存在的原子能力**，不重造轮子：
- 模型原生工具调用：`tool_definitions_for` + `ModelClient.chat(worker_transport="tool_use")`
  + `extract_tool_calls`（见 `worker_transport.py`）。
- 工具执行：注入的 `tool_runner.run_tool_calls`（`ToolExecutionGateway`）。
- 失败即 observation：`observation_from_tool_result` / `observation_from_exception`（见 `agent_harness.py`）。

刻意**不导入** `agent_loop_decision` / `execution_action` —— 立真身不产出 ExecutionAction 壳，
也不吐 `next_action` 枚举。灰度接入与老 FSM 的并存/退役见
`docs/zh/reports/architecture-conformance-audit-core-loop.md` §7。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from asteria_runtime.core.agent_harness import (
    ToolObservation,
    observation_from_exception,
    observation_from_tool_result,
)
from asteria_runtime.core.worker_transport import extract_tool_calls, tool_definitions_for
from asteria_runtime.models.base import ChatMessage, ChatRequest


class ToolRunner(Protocol):
    """立真身对工具执行层的最小契约（`ToolExecutionGateway.run_tool_calls` 即满足）。"""

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: Any,
        stop_on_failure: bool = True,
        stop_verification_on_fatal: bool = False,
    ) -> list[Any]:
        ...


class ChatClient(Protocol):
    def chat(self, request: ChatRequest) -> Any:
        ...


@dataclass(frozen=True)
class TurnEvent:
    """一步循环产生的可观察事件（narration/工具观察/完成/保险丝），供上层投影到主线程。"""

    kind: str  # "narration" | "tool_observation" | "final" | "fuse"
    iteration: int
    text: str = ""
    observations: list[ToolObservation] = field(default_factory=list)


@dataclass
class ModelDrivenTurnResult:
    status: str  # "completed" | "budget_exhausted"
    final_message: str
    iterations: int
    events: list[TurnEvent]
    observations: list[ToolObservation]


def run_model_driven_turn(
    *,
    model_client: ChatClient,
    tool_runner: ToolRunner,
    task: dict,
    context: Any,
    available_tools: list[str],
    system_prompt: str,
    user_prompt: str,
    model_tier: str = "strong",
    max_iterations: int = 8,
    extra_tool_specs: list[dict] | None = None,
    request_purpose: str = "task_execution",
    temperature: float = 0.2,
    max_output_tokens: int = 5000,
    on_event: Callable[[TurnEvent], None] | None = None,
) -> ModelDrivenTurnResult:
    """跑一条模型驱动的 tool-use 循环，直到模型停止调用工具或撞上保险丝。

    返回 `ModelDrivenTurnResult`：`status="completed"` 表示模型主动收尾（不再调工具），
    `status="budget_exhausted"` 表示撞上 `max_iterations` 保险丝（可 resume，不冒充语义完成/失败）。
    """

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]
    tool_defs = tool_definitions_for(available_tools, extra_tool_specs)
    events: list[TurnEvent] = []
    all_observations: list[ToolObservation] = []

    def emit(event: TurnEvent) -> None:
        events.append(event)
        if on_event is not None:
            on_event(event)

    nudged = False
    for iteration in range(1, max_iterations + 1):
        response = model_client.chat(
            ChatRequest(
                purpose=request_purpose,
                model_tier=model_tier,
                messages=list(messages),
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                worker_transport="tool_use",
                tools=tool_defs or None,
                metadata={
                    "task_id": task.get("task_id"),
                    "iteration": iteration,
                    "loop": "model_driven_turn",
                },
            )
        )
        narration = str(getattr(response, "content", "") or "").strip()
        if narration:
            emit(TurnEvent(kind="narration", iteration=iteration, text=narration))

        calls = extract_tool_calls(getattr(response, "raw_response", {}) or {})
        if not calls:
            # 模型只说话、不调工具 = 它认为本轮做完了。唯一的例外是弱模型的"过早收尾"：
            # 第一轮就停、任务还有明确产出、且尚无任何 observation —— 轻推一次（继续），
            # 而不是把没根据的 stop 当完成。推一次即止，之后完全尊重模型判断（ADR-0016：
            # 脚手架是护栏不是认知，且只在证据支持时介入）。
            if iteration == 1 and not nudged and not all_observations and _has_pending_work(task):
                nudged = True
                messages.append(ChatMessage(role="assistant", content=narration or "(no tool call)"))
                messages.append(ChatMessage(role="user", content=_grounding_nudge(task)))
                continue
            emit(TurnEvent(kind="final", iteration=iteration, text=narration))
            return ModelDrivenTurnResult(
                status="completed",
                final_message=narration,
                iterations=iteration,
                events=events,
                observations=all_observations,
            )

        # 执行模型选的工具。失败不抛、不进 repair 分支——一律作为 observation 回灌，模型自己决定下一步。
        observations = _execute(tool_runner, calls, task, context)
        all_observations.extend(observations)
        emit(TurnEvent(kind="tool_observation", iteration=iteration, observations=observations))

        messages.append(
            ChatMessage(role="assistant", content=_assistant_turn_text(narration, calls))
        )
        messages.append(ChatMessage(role="user", content=_observation_feedback(observations)))

    # 撞上保险丝：可 resume 的预算边界，不是"失败"也不是"完成"。
    emit(TurnEvent(kind="fuse", iteration=max_iterations))
    return ModelDrivenTurnResult(
        status="budget_exhausted",
        final_message="",
        iterations=max_iterations,
        events=events,
        observations=all_observations,
    )


def _execute(
    tool_runner: ToolRunner,
    calls: list[dict],
    task: dict,
    context: Any,
) -> list[ToolObservation]:
    """执行一批工具调用，把每个结果（含失败）转成 observation。工具层自身报错也化为 observation。"""
    try:
        results = tool_runner.run_tool_calls(calls, task, context, stop_on_failure=False)
    except Exception as exc:  # 工具网关自身异常同样只是 observation，绝不触发独立 repair 路径
        tool_name = str((calls[0] if calls else {}).get("tool_name") or "tool")
        return [observation_from_exception(tool_name=tool_name, exc=exc)]
    observations: list[ToolObservation] = []
    for call, result in zip(calls, results):
        tool_name = str(call.get("tool_name") or "tool")
        observations.append(observation_from_tool_result(tool_name=tool_name, result=result))
    return observations


def _observation_feedback(observations: list[ToolObservation]) -> str:
    lines = [obs.model_summary() for obs in observations]
    body = "\n".join(lines) if lines else "(no observation)"
    return (
        "Tool results (observations):\n"
        f"{body}\n"
        "Continue with more tool calls if the task is not complete. "
        "When the task is done and verified, reply with a short final message and NO tool calls."
    )


def _assistant_turn_text(narration: str, calls: list[dict]) -> str:
    summary = ", ".join(_call_signature(call) for call in calls)
    prefix = narration or "(worked via tools)"
    return f"{prefix}\n[called tools: {summary}]"


def _call_signature(call: dict) -> str:
    name = str(call.get("tool_name") or "tool")
    raw_args = call.get("args")
    args: dict = raw_args if isinstance(raw_args, dict) else {}
    key = next((k for k in ("path", "command") if k in args), None)
    return f"{name}({key}={args[key]})" if key else name


def _has_pending_work(task: dict) -> bool:
    for key in ("write_scope", "expected_artifacts", "validation_commands"):
        if [item for item in (task.get(key) or []) if item]:
            return True
    return False


def _grounding_nudge(task: dict) -> str:
    targets = [
        str(item)
        for key in ("write_scope", "expected_artifacts")
        for item in (task.get(key) or [])
        if item
    ]
    target_text = ", ".join(dict.fromkeys(targets)) or "the expected artifact"
    return (
        f"The task is not complete yet: {target_text} has not been produced. "
        "Use tool calls (e.g. write_file / edit_file) to produce it now. "
        "Do not end the turn before the expected artifact exists."
    )
