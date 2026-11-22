"""Local logical-call reconciliation; never infers network dispatch or retries."""

def unresolved_model_requests(
    prepared: list[dict], terminals: list[dict], run_id: str,
) -> tuple[list[dict], int]:
    starts: dict[str, dict] = {}
    for row in prepared:
        identity = row["request_attempt_id"]
        if not identity or identity in starts or row.get("run_id") not in (None, run_id):
            raise ValueError("ambiguous model request preparation identity or run scope")
        starts[identity] = row
    seen: set[str] = set()
    orphan = 0
    for row in terminals:
        identity = row.get("request_attempt_id")
        if identity is None:  # legacy terminal, no attribution invented
            continue
        if not identity or identity in seen or row.get("run_id") not in (None, run_id):
            raise ValueError("ambiguous model request terminal identity")
        seen.add(identity)
        start = starts.get(identity)
        if start is None:
            orphan += 1
            continue
        for field in ("run_id", "task_id", "purpose", "model_tier"):
            if row.get(field) != start.get(field):
                raise ValueError(f"conflicting model request {field}")
        # Configured provider/model names may differ from the server's echoed names.
    return [row for identity, row in starts.items() if identity not in seen], orphan
