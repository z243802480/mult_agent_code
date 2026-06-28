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
