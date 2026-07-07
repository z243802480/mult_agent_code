"""可插拔 worker 后端单测(LocalExecutor 实 / CloudSessionExecutor stub)。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from asteria_runtime.core.worker_executor import (
    CloudSessionExecutor,
    LocalExecutor,
    SubagentRequest,
    resolve_worker_executor,
)


class _FakeModel:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)

    def chat(self, _request):
        return self._responses.pop(0)


def _json_resp(narration: str, tool_calls=None, done: bool = False) -> SimpleNamespace:
    payload = {"narration": narration, "tool_calls": tool_calls or [], "done": done}
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), raw_response={})


class _FakeRunner:
    def run_tool_calls(self, calls, task, context, stop_on_failure=True, stop_verification_on_fatal=False):
        return [
            SimpleNamespace(ok=True, summary="ok", status="success", error=None, data={})
            for _ in calls
        ]


def _request() -> SubagentRequest:
    return SubagentRequest(
        role="coder",
        task={"task_id": "task-0001-sub-01", "allowed_tools": []},
        system_prompt="system",
        user_prompt="do the thing",
        available_tools=[],
        model_tier="strong",
        max_iterations=4,
    )


def test_local_executor_runs_child_loop_and_completes() -> None:
    model = _FakeModel([_json_resp("已完成", [], done=True)])
    outcome = LocalExecutor().run_subagent(
        _request(), model_client=model, tool_runner=_FakeRunner(), context=object()
    )
    assert outcome.ok is True
    assert outcome.status == "completed"
    assert outcome.data["backend"] == "local"


def test_cloud_session_executor_defers_without_running() -> None:
    outcome = CloudSessionExecutor().run_subagent(
        _request(), model_client=None, tool_runner=None, context=object()
    )
    assert outcome.ok is False
    assert outcome.status == "deferred"
    assert outcome.data["deferred"] is True
    assert "deferred" in outcome.summary


def test_resolve_worker_executor_picks_backend() -> None:
    assert resolve_worker_executor("local").backend_kind == "local"
    assert resolve_worker_executor("cloud_session").backend_kind == "cloud_session"
    assert resolve_worker_executor("remote").backend_kind == "cloud_session"
    # Unknown / empty defaults to local (never silently offloads).
    assert resolve_worker_executor("wat").backend_kind == "local"
    assert resolve_worker_executor("").backend_kind == "local"
