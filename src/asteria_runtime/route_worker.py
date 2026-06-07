from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from asteria_runtime.commands.route_command import RouteCommand


def handle_route_request(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    op = str(payload.get("op") or "route").strip().lower()
    if op != "route":
        raise ValueError(f"unsupported op: {op}")

    root = Path(str(payload.get("root") or ".")).resolve()
    message = str(payload.get("message") or "")
    requested_mode = str(payload.get("mode") or payload.get("requested_mode") or "auto")
    rules_only = bool(payload.get("rules_only"))
    router_mode = payload.get("router_mode")
    router_mode_override = str(router_mode).strip().lower() if router_mode else None
    include_catalog = bool(payload.get("include_catalog"))

    result = RouteCommand(
        root=root,
        message=message,
        requested_mode=requested_mode,
        use_model=not rules_only,
        router_mode_override=router_mode_override,
    ).run()
    response = {
        "id": request_id,
        "ok": True,
        **result.to_dict(include_catalog=include_catalog),
    }
    return response


def run_route_worker() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        request_id = None
        try:
            payload = json.loads(line)
            request_id = payload.get("id")
            response = handle_route_request(payload)
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_route_worker()
