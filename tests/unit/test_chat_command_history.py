from pathlib import Path

from asteria_runtime.commands.chat_command import ChatCommand


def _cmd(history: object) -> ChatCommand:
    return ChatCommand(Path("."), "current question", history=history)


def test_chat_history_defaults_to_empty_when_absent() -> None:
    # CLI stays single-shot: no history -> messages remain [system, user], behavior unchanged.
    assert _cmd(None).history == []
    assert _cmd("not-a-list").history == []


def test_chat_history_filters_roles_and_blanks() -> None:
    messages = _cmd(
        [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "system", "content": "drop me"},
            {"role": "user", "content": "   "},
            "not-a-dict",
        ]
    ).history
    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.content for m in messages] == ["a", "b"]


def test_chat_history_bounds_recent_turns_and_clips_length() -> None:
    long = "x" * 2000
    items = [{"role": "user", "content": f"u{i}"} for i in range(20)]
    items.append({"role": "assistant", "content": long})
    messages = _cmd(items).history

    assert len(messages) == ChatCommand._MAX_HISTORY_TURNS
    assert len(messages[-1].content) <= ChatCommand._MAX_HISTORY_CHARS + 1
    assert messages[-1].content.endswith("…")
