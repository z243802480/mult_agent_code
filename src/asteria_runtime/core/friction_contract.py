from __future__ import annotations

from typing import Any


DEFAULT_THRESHOLDS = {
    "decide": 2,
    "debug": 2,
    "resume": 2,
}


def evaluate_friction(
    friction: dict[str, Any] | None,
    *,
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Validate B6-style friction counters against steady-state thresholds."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    counts = {
        "decide": int((friction or {}).get("decide") or 0),
        "debug": int((friction or {}).get("debug") or 0),
        "resume": int((friction or {}).get("resume") or 0),
    }
    violations = [
        key
        for key, limit in limits.items()
        if counts.get(key, 0) > int(limit)
    ]
    ok = not violations
    return {
        "ok": ok,
        "counts": counts,
        "thresholds": limits,
        "violations": violations,
        "summary": (
            "Friction within thresholds."
            if ok
            else f"Friction exceeded: {', '.join(violations)}."
        ),
    }
