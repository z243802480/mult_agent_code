import json
from pathlib import Path

from asteria_runtime.commands.chat_command import ChatCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

from tests.integration.test_plan_command import FakePlanClient

pytestmark = __import__("pytest").mark.workflow


class CapturingChatClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content="当前 workspace 已初始化，可用 goal、plan、ask 推进任务。",
            finish_reason="stop",
            usage=TokenUsage(1, 2, 3),
            model_provider="fake",
            model_name="fake-chat",
            raw_response={},
        )


def test_chat_command_persists_capability_manifest_and_model_metadata(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()
    client = CapturingChatClient()

    ChatCommand(
        tmp_path,
        "当前 session 下一步是什么？",
        model_client=client,
    ).run()

    assert client.requests
    metadata = client.requests[0].metadata
    assert metadata["capability_manifest_hash"].startswith("sha256:")
    assert metadata["prompt_envelope_hash"].startswith("sha256:")
    assert metadata["context_envelope_hash"]

    envelope_path = (
        tmp_path / ".asteria" / "runs" / plan.run_id / "prompt_envelope_chat.json"
    )
    assert envelope_path.exists()
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert envelope["mode"] == "chat"
    assert envelope["capability_manifest"]["direct_tools"]
    user_payload = json.loads(client.requests[0].messages[-1].content)
    assert user_payload["capability_manifest"]["direct_tools"]
    assert user_payload["prompt_envelope"]["capability_manifest_hash"] == metadata[
        "capability_manifest_hash"
    ]
