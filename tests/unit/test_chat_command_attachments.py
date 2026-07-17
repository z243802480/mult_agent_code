import base64
import json
from pathlib import Path

import pytest

from asteria_runtime.commands.chat_command import (
    MAX_ATTACHMENT_BYTES,
    AttachmentError,
    ChatCommand,
)
from asteria_runtime.commands.init_command import InitCommand

PNG_BYTES = base64.b64decode(
    # 1x1 transparent PNG — smallest thing with a real image signature.
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _image(tmp_path: Path, name: str = "shot.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


def _cmd(tmp_path: Path, attachments: list[Path]) -> ChatCommand:
    return ChatCommand(tmp_path, "what number is this?", attachments=attachments)


def test_attachment_becomes_multimodal_parts_with_question_text(tmp_path: Path) -> None:
    messages = _cmd(tmp_path, [_image(tmp_path)])._attachment_messages()

    assert len(messages) == 1
    parts = messages[0].content
    assert isinstance(parts, list)
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    # The question rides along with the image so the model is not asked to guess why it got a picture.
    assert parts[-1] == {"type": "text", "text": "what number is this?"}


def test_relative_attachment_resolves_against_workspace_root(tmp_path: Path) -> None:
    _image(tmp_path, "rel.png")
    messages = ChatCommand(tmp_path, "q", attachments=[Path("rel.png")])._attachment_messages()
    assert len(messages) == 1


def test_missing_attachment_raises_rather_than_dropping_it(tmp_path: Path) -> None:
    with pytest.raises(AttachmentError, match="not found"):
        _cmd(tmp_path, [tmp_path / "nope.png"])._attachment_messages()


def test_unsupported_attachment_type_raises(tmp_path: Path) -> None:
    doc = tmp_path / "notes.txt"
    doc.write_text("hello", encoding="utf8")
    with pytest.raises(AttachmentError, match="Unsupported attachment type"):
        _cmd(tmp_path, [doc])._attachment_messages()


def test_oversized_attachment_raises(tmp_path: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + b"0" * (MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(AttachmentError, match="limit"):
        _cmd(tmp_path, [big])._attachment_messages()


def test_no_attachments_means_no_extra_messages(tmp_path: Path) -> None:
    assert ChatCommand(tmp_path, "q")._attachment_messages() == []


def _workspace(tmp_path: Path) -> Path:
    InitCommand(tmp_path).run()
    return tmp_path


def test_chat_without_vision_route_refuses_instead_of_answering_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The configured default route is text-only (a real probe showed the coding endpoint rejects
    # images with HTTP 400/1210). Answering anyway would mean replying about an unseen image.
    monkeypatch.setattr(
        "asteria_runtime.commands.chat_command.vision_route_configured", lambda: False
    )
    root = _workspace(tmp_path)
    result = ChatCommand(root, "what is this?", attachments=[_image(tmp_path)]).run()

    assert "no vision model route is configured" in result.answer
    assert any("AGENT_MODEL_VISION_PROVIDER" in action for action in result.next_actions)


def test_attachment_error_surfaces_as_refusal_not_a_crash(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = ChatCommand(root, "q", attachments=[tmp_path / "ghost.png"]).run()
    assert "Attachment not found" in result.answer


def test_json_envelope_stays_last_when_images_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of inserting images before the envelope, asserted on real messages.

    FakeModelClient and the acceptance scenarios read ``messages[-1].content`` as the JSON
    envelope; an image message appended last would silently break every one of them.
    """
    monkeypatch.setattr(
        "asteria_runtime.commands.chat_command.vision_route_configured", lambda: True
    )
    captured: dict = {}

    class _Spy:
        def chat(self, request):  # noqa: ANN001, ANN202
            captured["messages"] = list(request.messages)
            raise RuntimeError("stop after capture")

    root = _workspace(tmp_path)
    cmd = ChatCommand(root, "what number?", attachments=[_image(tmp_path)], model_client=_Spy())
    with pytest.raises(RuntimeError, match="stop after capture"):
        cmd.run()

    messages = captured["messages"]
    assert isinstance(messages[-1].content, str)
    json.loads(messages[-1].content)  # last message must still parse as the JSON envelope
    image_positions = [i for i, m in enumerate(messages) if isinstance(m.content, list)]
    assert image_positions == [len(messages) - 2]
