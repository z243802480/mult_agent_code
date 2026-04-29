import pytest

from agent_runtime.models.json_extractor import JsonExtractionError, parse_json_object


def test_parse_json_object_accepts_plain_json() -> None:
    assert parse_json_object('{"ok": true}') == {"ok": True}


def test_parse_json_object_strips_markdown_fence() -> None:
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_json_object_does_not_strip_fence_inside_json_string() -> None:
    content = '{"summary": "example ```python\\nprint(1)\\n```"}'

    assert parse_json_object(content) == {"summary": "example ```python\nprint(1)\n```"}


def test_parse_json_object_uses_last_object_after_thinking_text() -> None:
    content = """
<think>
I might mention an example {"ok": false} while reasoning.
</think>
{"ok": true}
"""

    assert parse_json_object(content) == {"ok": True}


def test_parse_json_object_handles_unclosed_thinking_prefix() -> None:
    content = '<think>Example {"draft": true}\nFinal answer: {"ok": true}'

    assert parse_json_object(content) == {"ok": True}


def test_parse_json_object_repairs_common_unquoted_keys() -> None:
    assert parse_json_object("{schema_version: '0.1.0', task_id: 'task-0001'}") == {
        "schema_version": "0.1.0",
        "task_id": "task-0001",
    }


def test_parse_json_object_rejects_missing_object() -> None:
    with pytest.raises(JsonExtractionError):
        parse_json_object("not json")
