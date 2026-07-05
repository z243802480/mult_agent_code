"""Unit tests for the CV-C model-authored closing recap helper."""

from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.run_recap import author_run_recap


@dataclass
class _StubResponse:
    content: str


class _StubModelClient:
    def __init__(self, content: str):
        self._content = content
        self.last_request = None

    def chat(self, request):
        self.last_request = request
        return _StubResponse(self._content)


class _BoomModelClient:
    def chat(self, request):  # noqa: ARG002
        raise RuntimeError("provider down")


def _validation(status: str = "passed", passed: int = 2, total: int = 2):
    return {"status": status, "passed": passed, "total": total}


def test_recap_returns_empty_without_model_client():
    assert (
        author_run_recap(
            model_client=None,
            goal="ship a fix",
            run_status="completed",
            steps=[("execute", "completed", "did the thing")],
            file_changes=[{"path": "src/a.py"}],
            validation=_validation(),
        )
        == ""
    )


def test_recap_returns_empty_on_model_failure():
    assert (
        author_run_recap(
            model_client=_BoomModelClient(),
            goal="ship a fix",
            run_status="completed",
            steps=[],
            file_changes=[],
            validation=_validation(),
        )
        == ""
    )


def test_recap_returns_model_prose_and_passes_context():
    client = _StubModelClient("Done — I updated src/a.py and all 2 checks passed.")
    text = author_run_recap(
        model_client=client,
        goal="修复登录缺陷",
        run_status="completed",
        steps=[("execute", "completed", "patched the handler")],
        file_changes=[{"path": "src/auth.py"}],
        validation=_validation(),
    )
    assert text == "Done — I updated src/a.py and all 2 checks passed."
    # Context handed to the model must carry the goal, status, verification and files.
    user_msg = client.last_request.messages[-1].content
    assert "修复登录缺陷" in user_msg
    assert "completed" in user_msg
    assert "src/auth.py" in user_msg
    assert "2/2" in user_msg


def test_recap_strips_markdown_scaffolding_and_clamps():
    client = _StubModelClient(
        "## Result\n- I finished the task.\nVerification: all checks passed."
    )
    text = author_run_recap(
        model_client=client,
        goal="g",
        run_status="completed",
        steps=[],
        file_changes=[],
        validation=_validation(),
    )
    assert "##" not in text
    assert not text.startswith("-")
    assert "I finished the task." in text
    assert "all checks passed." in text


def test_recap_clamps_overlong_output():
    client = _StubModelClient("word " * 400)
    text = author_run_recap(
        model_client=client,
        goal="g",
        run_status="completed",
        steps=[],
        file_changes=[],
        validation=None,
    )
    assert len(text) <= 601  # 600 cap + ellipsis


def test_recap_strips_reasoning_think_block_and_keeps_the_answer():
    # Reasoning models (MiniMax M2, the default medium tier) inline chain-of-thought in
    # <think>…</think>; the recap is the prose after it. The think block must never reach the thread.
    client = _StubModelClient(
        "<think>\nThe user asked me to add a flag. I created add.py and the test passed.\n"
        "Let me phrase a short recap.\n</think>\n\n已完成：新增 add.py 与测试，6/6 检查通过。"
    )
    text = author_run_recap(
        model_client=client,
        goal="加个 add 函数",
        run_status="completed",
        steps=[],
        file_changes=[],
        validation=_validation(),
    )
    assert "<think>" not in text
    assert "chain-of-thought" not in text.lower()
    assert text == "已完成：新增 add.py 与测试，6/6 检查通过。"


def test_recap_reasoning_only_truncation_falls_back_to_empty():
    # The model spent its whole budget thinking and never wrote the recap (unclosed <think>): we must
    # return "" so the caller keeps its structured fallback instead of leaking raw reasoning.
    client = _StubModelClient(
        "<think>\nLet me think about how to summarize this run. The task was to add a function and"
    )
    text = author_run_recap(
        model_client=client,
        goal="g",
        run_status="completed",
        steps=[],
        file_changes=[],
        validation=_validation(),
    )
    assert text == ""
