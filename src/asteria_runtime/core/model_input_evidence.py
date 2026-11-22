"""Content-free, bounded evidence of runtime feedback at request assembly."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
from typing import TYPE_CHECKING, Callable

from asteria_runtime.core.observation_receipt import observation_receipt

if TYPE_CHECKING:
    from asteria_runtime.core.agent_harness import ToolObservation
    from asteria_runtime.models.base import ChatMessage, ChatRequest

MAX_OBSERVATIONS = 64
_COUNTS = {"matched_feedback_messages", "unmatched_feedback_messages", "observation_count",
           "unidentified_observations", "omitted_observations"}
_ROW_KEYS = {"tool_call_id", "tool_name", "message_index", "feedback_sha256", "payload_sha256",
             "receipt_sha256", "payload_included", "dispatch_state"}
_DISPATCH = {"unknown", "dispatched", "not_dispatched"}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf8")).hexdigest()


def messages_sha256(messages: list[ChatMessage]) -> str:
    return _digest([message.to_payload() for message in messages])


def build_input_evidence(
    messages: list[ChatMessage], feedback_index: list[tuple[int, list[ToolObservation]]],
    render: Callable[[list[ToolObservation], bool], str],
) -> dict:
    positions = Counter(index for index, _ in feedback_index if type(index) is int)
    candidates: list[tuple[int, ToolObservation, bool, str]] = []
    matched = unmatched = 0
    for index, observations in feedback_index:
        if type(index) is not int or not 0 <= index < len(messages) or positions[index] != 1:
            unmatched += 1
            continue
        message = messages[index]
        if message.role != "user" or message.name is not None or not isinstance(message.content, str):
            unmatched += 1
            continue
        full = message.content == render(observations, True)
        if not full and message.content != render(observations, False):
            unmatched += 1
            continue
        matched += 1
        digest = hashlib.sha256(message.content.encode("utf8")).hexdigest()
        candidates.extend((index, obs, full, digest) for obs in observations)
    identities = Counter(obs.data.get("tool_call_id") for _, obs, _, _ in candidates
                         if isinstance(obs.data.get("tool_call_id"), str))
    eligible = [(index, obs, full, digest) for index, obs, full, digest in candidates
                if isinstance(obs.data.get("tool_call_id"), str) and 0 < len(obs.data["tool_call_id"]) <= 160
                and identities[obs.data["tool_call_id"]] == 1
                and isinstance(obs.tool_name, str) and 0 < len(obs.tool_name) <= 128]
    entries = [{"tool_call_id": obs.data["tool_call_id"], "tool_name": obs.tool_name, "message_index": index,
                "feedback_sha256": digest, "payload_sha256": hashlib.sha256(obs.payload.encode("utf8")).hexdigest(),
                "payload_included": full and bool(obs.payload), "receipt_sha256": _digest(observation_receipt(obs)),
                "dispatch_state": obs.dispatch_state if obs.dispatch_state in _DISPATCH else "unknown"}
               for index, obs, full, digest in eligible[-MAX_OBSERVATIONS:]]
    return {"scope": "request_assembly_only", "messages_sha256": messages_sha256(messages),
            "matched_feedback_messages": matched, "unmatched_feedback_messages": unmatched,
            "observation_count": len(candidates), "unidentified_observations": len(candidates) - len(eligible),
            "omitted_observations": max(0, len(eligible) - MAX_OBSERVATIONS), "observations": entries}


def _is_digest(value) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _valid(trace) -> bool:
    if (not isinstance(trace, dict) or set(trace) != _COUNTS | {"scope", "messages_sha256", "observations"}
            or trace.get("scope") != "request_assembly_only" or not _is_digest(trace.get("messages_sha256"))
            or any(type(trace.get(key)) is not int or not 0 <= trace[key] <= 1_000_000 for key in _COUNTS)):
        return False
    rows = trace["observations"]
    if not isinstance(rows, list) or len(rows) > MAX_OBSERVATIONS:
        return False
    for row in rows:
        if (not isinstance(row, dict) or set(row) != _ROW_KEYS
                or any(not isinstance(row[key], str) or not 0 < len(row[key]) <= limit
                       for key, limit in (("tool_call_id", 160), ("tool_name", 128)))
                or any(not _is_digest(row[key]) for key in ("feedback_sha256", "payload_sha256", "receipt_sha256"))
                or type(row["message_index"]) is not int or not 0 <= row["message_index"] <= 1_000_000
                or type(row["payload_included"]) is not bool
                or not isinstance(row["dispatch_state"], str) or row["dispatch_state"] not in _DISPATCH):
            return False
    return (len({row["tool_call_id"] for row in rows}) == len(rows)
            and trace["observation_count"] == len(rows) + trace["unidentified_observations"] + trace["omitted_observations"])


def persisted_input_evidence(request: ChatRequest) -> dict | None:
    """Recheck actual messages after routing/wrappers; no old linkage survives a change."""
    if "input_evidence" not in request.metadata:
        return None
    trace = request.metadata["input_evidence"]
    actual = messages_sha256(request.messages)
    original = trace.get("messages_sha256") if isinstance(trace, dict) else None
    result: dict = {"scope": "request_assembly_only", "messages_sha256": actual,
              "assembly_messages_sha256": original if _is_digest(original) else None,
              "status": "invalid", "observations": []}
    if _valid(trace):
        if actual == original:
            result.update(deepcopy(trace), status="matched")
        else:
            result["status"] = "messages_changed"
    return result
