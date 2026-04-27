from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class HttpTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: dict


class HttpTransport:
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout_seconds: int,
    ) -> HttpResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                return HttpResponse(response.status, json.loads(response_body))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(error_body)
            except json.JSONDecodeError:
                parsed = {"error": error_body}
            return HttpResponse(exc.code, parsed)
        except urllib.error.URLError as exc:
            raise HttpTransportError(str(exc)) from exc
        except TimeoutError as exc:
            raise HttpTransportError("request timed out") from exc
