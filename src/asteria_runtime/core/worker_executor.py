"""可插拔的 worker 执行后端(ADR-0022 · 集群大脑骨架)。

一个专家子代理"在哪运行"应当是可插拔的:**本机进程**(现在)/ **云 session**(未来·北极星)。
`spawn_subagent` 只描述子任务(SubagentRequest),由 `resolve_worker_executor` 选后端执行,回一个
统一的 SubagentOutcome。这样把"集群大脑"的运行时隔离/云卸载做成**接口现在就焊死、实现分期填**:
LocalExecutor 是实(就是当前的本机立真身子循环),CloudSessionExecutor 是 stub(复用既有
`remote_background_adapter`,只记卸载意图·返回 deferred),真远程运行时是 Part B(B3)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from asteria_runtime.core.model_driven_turn import TurnEvent, run_model_driven_turn


@dataclass(frozen=True)
class SubagentRequest:
    """把一个专家子任务的执行所需全部打包 —— 与"在哪运行"无关。"""

    role: str
    task: dict
    system_prompt: str
    user_prompt: str
    available_tools: list[str]
    model_tier: str
    max_iterations: int


@dataclass(frozen=True)
class SubagentOutcome:
    """后端无关的子代理结果(只回摘要,不回子上下文)。"""

    ok: bool
    status: str  # "completed" | "budget_exhausted" | "deferred"
    summary: str
    iterations: int
    data: dict = field(default_factory=dict)


class WorkerExecutor(Protocol):
    backend_kind: str

    def run_subagent(
        self,
        request: SubagentRequest,
        *,
        model_client: Any,
        tool_runner: Any,
        context: Any,
        on_event: Callable[[TurnEvent], None] | None = None,
    ) -> SubagentOutcome:
        ...


class LocalExecutor:
    """本机进程:直接跑一个有界立真身子循环(这就是当前行为,现在放到可插拔 seam 之后)。"""

    backend_kind = "local"

    def run_subagent(
        self,
        request: SubagentRequest,
        *,
        model_client: Any,
        tool_runner: Any,
        context: Any,
        on_event: Callable[[TurnEvent], None] | None = None,
    ) -> SubagentOutcome:
        result = run_model_driven_turn(
            model_client=model_client,
            tool_runner=tool_runner,
            task=request.task,
            context=context,
            available_tools=request.available_tools,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            model_tier=request.model_tier,
            max_iterations=request.max_iterations,
            transport="json",
            on_event=on_event,
        )
        # Surface what the child actually changed so the LEAD's completion contract can credit the
        # delegated artifacts (shared-workspace skeleton). Same artifact_refs extraction the lead
        # uses on its own observations; failed/denied writes are excluded via the ok guard.
        child_changed = [
            str(ref)
            for observation in result.observations
            if getattr(observation, "ok", False)
            for ref in getattr(observation, "artifact_refs", [])
            if ref
        ]
        return SubagentOutcome(
            ok=result.status == "completed",
            status=result.status,
            summary=result.final_message or "subagent finished",
            iterations=result.iterations,
            data={
                "role": request.role,
                "backend": self.backend_kind,
                "changed_files": child_changed,
            },
        )


class CloudSessionExecutor:
    """STUB(北极星 B3):把子代理卸载到隔离的云 session 执行。复用既有 `remote_background_adapter`
    stub —— 记下卸载意图、返回 deferred。接口现在就焊死,真远程运行时是 Part B。默认永不启用
    (policy 明确选 cloud_session 才走这里),故对本机/离线零影响。

    实现候选(调研 2026-07-13·见记忆 `cubesandbox-cloud-sandbox-candidate`):**腾讯云 CubeSandbox**
    (github.com/TencentCloud/CubeSandbox·Apache 2.0·RustVMM+KVM MicroVM 硬件隔离·**E2B SDK 兼容**·
    <60ms 冷启动)——国产化对齐(glm/minimax 定位·不接 Anthropic/OpenAI)、真 OS 级隔离。真做云执行
    时优先接 E2B 兼容层(不锁死 provider)而非自造沙箱。**注**:CubeSandbox 是 Linux/KVM 云集群服务,
    **不适合本地 Windows 缺口**(那块按定位维持轻量硬化);它对口的正是本 stub 这条云路。"""

    backend_kind = "cloud_session"

    def __init__(self, validator: Any = None) -> None:
        self._validator = validator

    def run_subagent(
        self,
        request: SubagentRequest,
        *,
        model_client: Any,
        tool_runner: Any,
        context: Any,
        on_event: Callable[[TurnEvent], None] | None = None,
    ) -> SubagentOutcome:
        # Record the offload intent via the existing cloud stub (best-effort; never break the run).
        try:
            from asteria_runtime.core.remote_background_adapter import start_remote_background_stub

            root = getattr(context, "root", None)
            validator = self._validator or getattr(context, "validator", None)
            if root is not None and validator is not None:
                start_remote_background_stub(
                    root,
                    f"subagent:{request.role}:{request.task.get('task_id')}",
                    validator,
                )
        except Exception:  # noqa: BLE001 - stub bookkeeping must not break a run
            pass
        return SubagentOutcome(
            ok=False,
            status="deferred",
            summary="cloud session offload deferred (stub — local runtime only)",
            iterations=0,
            data={"role": request.role, "backend": self.backend_kind, "deferred": True},
        )


def resolve_worker_executor(backend_kind: str, *, validator: Any = None) -> WorkerExecutor:
    """按后端类型选执行器;默认(及任何未知值)= 本机。云 session 是 opt-in stub。"""
    if str(backend_kind or "").strip().lower() in {"cloud", "cloud_session", "remote"}:
        return CloudSessionExecutor(validator=validator)
    return LocalExecutor()
