import pytest

from agent_runtime.models.http_transport import HttpTransport, HttpTransportError


class FakeResponse:
    status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""


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
