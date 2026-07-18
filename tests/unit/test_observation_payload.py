"""Regression: the model must SEE what a tool returned.

A dogfood run surfaced a foundational loop bug — the model made 46 tool calls (read_file ×11,
run_command ×10, ...) and ZERO writes on a trivial edit task, then blocked on "no artifact
produced". Root cause: observation feedback echoed only a summary line ("read_file ok: Read file:
x") and never the file content or command stdout, so the model was blind to every read and looped
re-reading. These tests pin that tool output now reaches the model, bounded, with line anchors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from asteria_runtime.core.agent_harness import observation_from_tool_result
from asteria_runtime.core.model_driven_turn import _observation_feedback
from asteria_runtime.tools.base import ToolResult
from asteria_runtime.tools.file_tools import ReadFileTool


def _feedback(tool_name: str, data: dict) -> str:
    obs = observation_from_tool_result(tool_name=tool_name, result=ToolResult(ok=True, summary="s", data=data))
    return _observation_feedback([obs], transport="json")


def test_read_file_content_reaches_the_model_with_line_numbers() -> None:
    fb = _feedback(
        "read_file",
        {"content": "alpha\nBETA_MARKER", "line_start": 40, "line_end": 41, "total_lines": 100},
    )
    assert "BETA_MARKER" in fb
    assert "40\talpha" in fb and "41\tBETA_MARKER" in fb


def test_run_command_stdout_reaches_the_model() -> None:
    assert "OUT_MARKER" in _feedback("run_command", {"stdout": "OUT_MARKER", "returncode": 0})


def test_search_matches_and_paths_reach_the_model() -> None:
    assert "hit.py:12" in _feedback("search_text", {"matches": ["hit.py:12: found"]})
    assert "a/b.py" in _feedback("find_files", {"paths": ["a/b.py", "c/d.py"]})


def test_write_file_content_is_not_echoed_back() -> None:
    # You don't need to re-read what you just wrote; echoing it back only wastes context.
    fb = _feedback("write_file", {"path": "x.py", "content": "SECRET_BODY"})
    assert "SECRET_BODY" not in fb


def test_payload_is_bounded() -> None:
    fb = _feedback("run_command", {"stdout": "x" * 50_000})
    assert "truncated" in fb and len(fb) < 10_000


# --- read_file windowing ---------------------------------------------------------------------


def _ctx(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(root=tmp_path, policy={"protected_paths": []})


def test_read_small_file_returns_exact_bytes(tmp_path: Path) -> None:
    # Whole small file must keep exact content (trailing newline) so apply_patch keeps matching.
    f = tmp_path / "s.txt"
    f.write_text("line1\nline2\n", encoding="utf-8")
    r = ReadFileTool().run(_ctx(tmp_path), "s.txt")
    assert r.ok and r.data["content"] == "line1\nline2\n"
    assert r.data["total_lines"] == 2


def test_read_large_file_auto_windows(tmp_path: Path) -> None:
    big = "\n".join(f"L{i}" for i in range(1, 2001))
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    r = ReadFileTool().run(_ctx(tmp_path), "big.txt")
    assert r.ok
    assert r.data["line_start"] == 1 and r.data["line_end"] == ReadFileTool.DEFAULT_WINDOW
    assert r.data["total_lines"] == 2000
    assert "of 2000" in r.summary


def test_read_offset_limit_pages(tmp_path: Path) -> None:
    body = "\n".join(f"L{i}" for i in range(1, 101))
    (tmp_path / "p.txt").write_text(body, encoding="utf-8")
    r = ReadFileTool().run(_ctx(tmp_path), "p.txt", offset=50, limit=3)
    assert r.ok
    assert r.data["content"] == "L50\nL51\nL52"
    assert r.data["line_start"] == 50 and r.data["line_end"] == 52
