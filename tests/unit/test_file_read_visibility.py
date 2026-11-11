"""The model can follow visible pages without silently skipping unread file text."""

from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from asteria_runtime.core.agent_harness import observation_from_tool_result
from asteria_runtime.core.context_slimming import project_review_evidence
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.tools.base import ToolResult
from asteria_runtime.tools.file_tools import ReadFileTool


def observe(result):
    return observation_from_tool_result(tool_name="read_file", result=result)


def numbered(payload):
    return [(int(n), text) for n, text in re.findall(r"^(\d+)\t(.*)$", payload, re.MULTILINE)]


def context(root):
    return SimpleNamespace(root=root, policy={"protected_paths": []})


def test_whole_file_header_uses_the_actual_visible_last_line():
    result = ToolResult(ok=True, summary="Read file", data={"content": "a\nb\n", "total_lines": 2})
    before = deepcopy(result.data)
    payload = observe(result).payload
    assert "visible lines 1-2 of 2" in payload and "None" not in payload
    assert numbered(payload) == [(1, "a"), (2, "b")]
    assert "next_offset=" not in payload
    assert result.data == before


def test_truncated_window_announces_what_is_visible_and_the_first_unshown_line():
    data = {"content": "\n".join("x" * 100 for _ in range(300)),
            "line_start": 390, "line_end": 689, "total_lines": 1000}
    payload = observe(ToolResult(ok=True, summary="Read window", data=data)).payload
    shown = numbered(payload)
    assert len(payload) <= 6000
    assert shown and all(text == "x" * 100 for _, text in shown)
    end = shown[-1][0]
    assert end < 689 and f"visible lines 390-{end} of 1000" in payload
    assert f"next_offset={end + 1}" in payload
    assert "partial" not in payload


def test_following_real_tool_feedback_pages_every_line_once(tmp_path: Path):
    lines = [f"record-{i:04d}|" + "字" * 55 for i in range(1, 701)]
    target = tmp_path / "records.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    original = target.read_bytes()
    reader, ctx = ReadFileTool(), context(tmp_path)
    found, offset = [], 1
    for _ in range(30):
        result = reader.run(ctx, "records.txt", offset=offset, limit=800)
        obs = observe(result)
        feedback = _observation_feedback([obs], transport="json")
        page = numbered(obs.payload)
        assert page and page[0][0] == offset
        assert len(obs.payload) <= 6000 and obs.payload in feedback
        assert f"visible lines {page[0][0]}-{page[-1][0]} of 700" in obs.payload
        found.extend(page)
        hint = re.search(r"next_offset=(\d+)", feedback)
        if hint is None:
            break
        offset = int(hint[1])
        assert offset == page[-1][0] + 1
    else:
        pytest.fail("pagination did not reach EOF")
    assert found == list(enumerate(lines, 1))
    assert target.read_bytes() == original


def test_first_unshown_long_line_is_not_skipped():
    result = ToolResult(ok=True, summary="Read", data={
        "content": "first\nsecond\n" + "x" * 20000 + "\nlast", "total_lines": 4})
    payload = observe(result).payload
    assert numbered(payload) == [(1, "first"), (2, "second")]
    assert "visible lines 1-2 of 4" in payload and "next_offset=3" in payload


@pytest.mark.parametrize("byte_limited", [False, True])
def test_partial_single_line_is_explicit_and_never_skipped(tmp_path: Path, byte_limited):
    (tmp_path / "long.txt").write_text("界" * 10000 + "\nlast\n", encoding="utf-8")
    reader = ReadFileTool(max_bytes=32) if byte_limited else ReadFileTool()
    payload = observe(reader.run(context(tmp_path), "long.txt")).payload
    assert len(payload) <= 6000 and numbered(payload)[0][0] == 1
    assert "partial_line=1" in payload and "not fully read" in payload
    assert "next_offset=" not in payload
    assert "smaller limit" not in payload


def test_byte_limited_partial_tail_is_not_marked_as_fully_read(tmp_path: Path):
    (tmp_path / "long.txt").write_text("complete\n" + "界" * 100 + "\nend\n", encoding="utf-8")
    result = ReadFileTool(max_bytes=24).run(context(tmp_path), "long.txt")
    assert result.data["byte_truncated"]
    payload = observe(result).payload
    assert numbered(payload)[0] == (1, "complete")
    assert "partial_line=2" in payload and "next_offset=" not in payload


def test_byte_limit_at_line_boundary_offers_the_next_line(tmp_path: Path):
    (tmp_path / "lines.txt").write_text("aaa\nbbb\nccc\n", encoding="utf-8")
    result = ReadFileTool(max_bytes=8).run(context(tmp_path), "lines.txt")
    assert not result.data["byte_truncated"] and result.data["has_more"]
    payload = observe(result).payload
    assert numbered(payload) == [(1, "aaa"), (2, "bbb")]
    assert "of unknown" in payload and "next_offset=3" in payload
    assert "partial_line=" not in payload


def test_byte_limit_with_no_room_for_a_multibyte_character_does_not_repeat_the_prior_line(tmp_path):
    (tmp_path / "lines.txt").write_text("aaa\nbbb\n" + "界" * 20 + "\nend\n", encoding="utf-8")
    result = ReadFileTool(max_bytes=9).run(context(tmp_path), "lines.txt")
    assert result.data["byte_truncated"] and result.data["content"] == "aaa\nbbb\n"
    payload = observe(result).payload
    assert numbered(payload) == [(1, "aaa"), (2, "bbb")]
    assert "next_offset=3" in payload and "partial_line=2" not in payload


def test_byte_limited_window_can_contain_no_visible_character(tmp_path):
    (tmp_path / "lines.txt").write_text("界" * 20, encoding="utf-8")
    result = ReadFileTool(max_bytes=1).run(context(tmp_path), "lines.txt")
    assert result.data["byte_truncated"] and result.data["content"] == ""
    payload = observe(result).payload
    assert "partial_line=1" in payload and "empty file" not in payload
    assert "next_offset=" not in payload


@pytest.mark.parametrize("offset", [None, 50])
def test_empty_file_or_past_eof_has_no_fictional_range(tmp_path: Path, offset):
    (tmp_path / "empty.txt").write_text("" if offset is None else "a\nb\n", encoding="utf-8")
    payload = observe(ReadFileTool().run(context(tmp_path), "empty.txt", offset=offset)).payload
    assert payload and ("empty file" in payload or "no lines" in payload)
    assert "None" not in payload and "next_offset=" not in payload
    assert not numbered(payload)


def test_missing_content_is_not_manufactured_as_an_empty_file():
    payload = observe(ToolResult(ok=False, summary="Unavailable", data={"path": "missing"})).payload
    assert payload == ""


def test_review_keeps_legacy_file_payload_even_when_the_renderer_changes():
    row = {"observation": {"tool_name": "read_file", "data": {"path": "old.py", "total_lines": 2},
                            "payload": "(lines 1-None of 2)\n1\tlegacy bytes\n2\tmore bytes"}}
    projected = project_review_evidence({"tool_observations": [row]})
    assert projected["tool_observations"][0]["observation"]["payload"] == row["observation"]["payload"]
