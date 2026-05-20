from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from asteria_runtime.models.base import StreamingTelemetry
from asteria_runtime.models.studio_event_sink import studio_model_event_sink


class HttpTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: dict


@dataclass(frozen=True)
class HttpStreamingResponse:
    status_code: int
    body: dict
    telemetry: StreamingTelemetry


class HttpTransport:
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
    ) -> HttpResponse:
        sink = studio_model_event_sink()
        provider = _provider_from_url(url)
        model = str(payload.get("model") or "") or None
        sink.model_start(provider=provider, model=model, mode="non_streaming")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                try:
                    parsed_body = json.loads(response_body)
                except json.JSONDecodeError as exc:
                    preview = response_body[:200] if response_body else "<empty response>"
                    error = f"HTTP {response.status} returned non-JSON body: {preview}"
                    sink.model_error(provider=provider, model=model, error=error)
                    raise HttpTransportError(error) from exc
                content = _first_message_content(parsed_body)
                if content:
                    sink.model_delta(content, provider=provider, model=parsed_body.get("model") or model)
                sink.model_end(
                    provider=provider,
                    model=parsed_body.get("model") or model,
                    telemetry={"mode": "non_streaming"},
                )
                return HttpResponse(response.status, parsed_body)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(error_body)
            except json.JSONDecodeError:
                parsed = {"error": error_body}
            sink.model_error(provider=provider, model=model, error=f"HTTP {exc.code}: {error_body[:500]}")
            return HttpResponse(exc.code, parsed)
        except urllib.error.URLError as exc:
            sink.model_error(provider=provider, model=model, error=str(exc))
            raise HttpTransportError(str(exc)) from exc
        except TimeoutError as exc:
            sink.model_error(provider=provider, model=model, error="request timed out")
            raise HttpTransportError("request timed out") from exc

    def post_json_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
        idle_timeout_seconds: int,
        deadline_seconds: int | None = None,
    ) -> HttpStreamingResponse:
        sink = studio_model_event_sink()
        provider = _provider_from_url(url)
        requested_model = str(payload.get("model") or "") or None
        sink.model_start(provider=provider, model=requested_model, mode="streaming")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.monotonic()
        deadline_at = started + deadline_seconds if deadline_seconds else None
        chunks: list[str] = []
        chunk_count = 0
        first_chunk_ms: int | None = None
        last_chunk_ms: int | None = None
        finish_reason: str | None = None
        model: str | None = None
        usage: dict | None = None
        try:
            with urllib.request.urlopen(request, timeout=idle_timeout_seconds) as response:
                for raw_line in response:
                    now = time.monotonic()
                    if deadline_at is not None and now > deadline_at:
                        sink.model_error(provider=provider, model=requested_model, error="stream deadline exceeded")
                        raise HttpTransportError("stream deadline exceeded")
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        error = f"stream returned non-JSON event: {data[:120]}"
                        sink.model_error(provider=provider, model=requested_model, error=error)
                        raise HttpTransportError(error) from exc
                    model = event.get("model") or model
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content is None:
                        continue
                    sink.model_delta(str(content), provider=provider, model=model or requested_model)
                    chunks.append(str(content))
                    chunk_count += 1
                    elapsed_ms = int((now - started) * 1000)
                    first_chunk_ms = first_chunk_ms if first_chunk_ms is not None else elapsed_ms
                    last_chunk_ms = elapsed_ms
                duration_ms = int((time.monotonic() - started) * 1000)
                telemetry = StreamingTelemetry(
                    requested=True,
                    supported=True,
                    mode="streaming",
                    first_chunk_ms=first_chunk_ms,
                    last_chunk_ms=last_chunk_ms,
                    duration_ms=duration_ms,
                    chunk_count=chunk_count,
                    idle_timeout_ms=idle_timeout_seconds * 1000,
                    deadline_ms=deadline_seconds * 1000 if deadline_seconds else None,
                    finish_reason=finish_reason,
                )
                sink.model_end(
                    provider=provider,
                    model=model or requested_model,
                    telemetry=telemetry.to_dict(),
                )
                return HttpStreamingResponse(
                    response.status,
                    {
                        "model": model,
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "".join(chunks)},
                                "finish_reason": finish_reason,
                            }
                        ],
                        "usage": usage or {},
                    },
                    telemetry,
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(error_body)
            except json.JSONDecodeError:
                parsed = {"error": error_body}
            sink.model_error(provider=provider, model=requested_model, error=f"HTTP {exc.code}: {error_body[:500]}")
            return HttpStreamingResponse(
                exc.code,
                parsed,
                StreamingTelemetry(
                    requested=True,
                    supported=False,
                    mode="streaming_failed",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    idle_timeout_ms=idle_timeout_seconds * 1000,
                    deadline_ms=deadline_seconds * 1000 if deadline_seconds else None,
                    error_type="http_error",
                ),
            )
        except urllib.error.URLError as exc:
            sink.model_error(provider=provider, model=requested_model, error=str(exc))
            raise HttpTransportError(str(exc)) from exc
        except TimeoutError as exc:
            sink.model_error(provider=provider, model=requested_model, error="stream request timed out")
            raise HttpTransportError("stream request timed out") from exc


def _first_message_content(body: dict) -> str | None:
    choices = body.get("choices") or []
    if not choices:
        return None
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    return str(content) if content is not None else None


def _provider_from_url(url: str) -> str:
    lowered = url.lower()
    if "minimax" in lowered:
        return "minimax"
    if "bigmodel" in lowered or "zhipu" in lowered or "z.ai" in lowered:
        return "glm"
    if "openai" in lowered:
        return "openai"
    return "openai-compatible"
