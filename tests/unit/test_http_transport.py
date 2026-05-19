import pytest

from asteria_runtime.models.http_transport import HttpTransport, HttpTransportError


class FakeResponse:
    status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""


class FakeStreamResponse:
    status = 200

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(
            [
                b'data: {"model":"stream-model","choices":[{"delta":{"content":"{\\"ok\\""},"finish_reason":null}]}\n\n',
                b'data: {"choices":[{"delta":{"content":": true}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n',
                b"data: [DONE]\n\n",
            ]
        )


def test_http_transport_reports_success_status_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(HttpTransportError, match="non-JSON body"):
        HttpTransport().post_json(
            "https://example.test/v1/chat/completions",
            headers={},
            payload={"ok": True},
            timeout_seconds=1,
        )


def test_http_transport_parses_openai_style_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: int) -> FakeStreamResponse:
        return FakeStreamResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = HttpTransport().post_json_stream(
        "https://example.test/v1/chat/completions",
        headers={},
        payload={"stream": True},
        timeout_seconds=5,
        idle_timeout_seconds=2,
        deadline_seconds=5,
    )

    assert response.body["choices"][0]["message"]["content"] == '{"ok": true}'
    assert response.body["usage"]["total_tokens"] == 3
    assert response.telemetry.requested is True
    assert response.telemetry.chunk_count == 2
    assert response.telemetry.idle_timeout_ms == 2000
