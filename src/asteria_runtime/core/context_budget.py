from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from typing import Any, Iterable

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ContextPressure:
    estimated_tokens: int
    window_tokens: int
    ratio: float
    status: str
    compaction_threshold: float
    hard_stop_threshold: float

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "window_tokens": self.window_tokens,
            "ratio": self.ratio,
            "status": self.status,
            "compaction_threshold": self.compaction_threshold,
            "hard_stop_threshold": self.hard_stop_threshold,
        }


@dataclass(frozen=True)
class ContextEstimate:
    total_tokens: int
    sections: dict[str, int]
    duplicate_content_hashes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "sections": dict(sorted(self.sections.items())),
            "duplicate_content_hashes": list(self.duplicate_content_hashes),
        }


@dataclass(frozen=True)
class ContextBudgetSnapshot:
    snapshot_id: str
    run_id: str | None
    task_id: str
    created_at: str
    scope: str
    runtime_profile_id: str
    context_mount_id: str
    worker_kind: str
    isolation_policy: str
    parent_worker_invocation_id: str | None
    parent_runtime_profile_id: str | None
    estimated_tokens: int
    sections: dict[str, int]
    duplicate_content_hashes: list[str]
    duplicate_estimated_tokens: int
    duplicate_ref_count: int
    context_window_tokens: int
    context_window_ratio: float
    pressure_status: str
    compaction_threshold: float
    hard_stop_threshold: float
    compact_boundary: dict[str, Any]
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "scope": self.scope,
            "runtime_profile_id": self.runtime_profile_id,
            "context_mount_id": self.context_mount_id,
            "worker_kind": self.worker_kind,
            "isolation_policy": self.isolation_policy,
            "parent_worker_invocation_id": self.parent_worker_invocation_id,
            "parent_runtime_profile_id": self.parent_runtime_profile_id,
            "estimated_tokens": self.estimated_tokens,
            "sections": dict(sorted(self.sections.items())),
            "duplicate_content_hashes": list(self.duplicate_content_hashes),
            "duplicate_estimated_tokens": self.duplicate_estimated_tokens,
            "duplicate_ref_count": self.duplicate_ref_count,
            "context_window_tokens": self.context_window_tokens,
            "context_window_ratio": self.context_window_ratio,
            "pressure_status": self.pressure_status,
            "compaction_threshold": self.compaction_threshold,
            "hard_stop_threshold": self.hard_stop_threshold,
            "compact_boundary": dict(self.compact_boundary),
            "evidence_refs": list(self.evidence_refs),
        }


def estimate_request_context_tokens(messages: Iterable[Any]) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(getattr(message, "role", ""))
        total += estimate_text_tokens(getattr(message, "content", ""))
        total += 4
    return max(1, total)


def estimate_request_context(request: Any) -> ContextEstimate:
    """Estimate request context with coarse section attribution.

    The estimator intentionally stays provider-agnostic. It gives reports a stable
    explanation surface without storing raw prompt content.
    """

    sections: dict[str, int] = {}
    seen_hashes: dict[str, int] = {}
    metadata = getattr(request, "metadata", {}) or {}
    for message in getattr(request, "messages", []) or []:
        role_tokens = estimate_text_tokens(getattr(message, "role", ""))
        content = str(getattr(message, "content", "") or "")
        tokens = role_tokens + estimate_text_tokens(content) + 4
        section = _section_for_message(message, content, metadata)
        sections[section] = sections.get(section, 0) + tokens
        digest = _content_hash(content)
        if digest:
            seen_hashes[digest] = seen_hashes.get(digest, 0) + 1
    duplicate_hashes = sorted(hash_ for hash_, count in seen_hashes.items() if count > 1)
    total = max(1, sum(sections.values()))
    return ContextEstimate(
        total_tokens=total,
        sections={key: value for key, value in sections.items() if value > 0},
        duplicate_content_hashes=duplicate_hashes[:10],
    )


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        codepoint = ord(char)
        if (
            0x4E00 <= codepoint <= 0x9FFF
            or 0x3400 <= codepoint <= 0x4DBF
            or 0x3040 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
        ):
            cjk += 1
        else:
            other += 1
    return cjk + ceil(other / 4)


def context_pressure(policy: dict, estimated_tokens: int) -> ContextPressure:
    context = policy.get("context") or {}
    window_tokens = max(1, int(context.get("model_context_window_tokens", 200_000)))
    compaction_threshold = float(context.get("compaction_threshold", 0.75))
    hard_stop_threshold = float(context.get("hard_stop_threshold", 0.9))
    ratio = max(0.0, estimated_tokens / window_tokens)
    if ratio >= 1:
        status = "exceeded"
    elif ratio >= hard_stop_threshold:
        status = "hard_stop"
    elif ratio >= compaction_threshold:
        status = "near_limit"
    else:
        status = "within_budget"
    return ContextPressure(
        estimated_tokens=estimated_tokens,
        window_tokens=window_tokens,
        ratio=ratio,
        status=status,
        compaction_threshold=compaction_threshold,
        hard_stop_threshold=hard_stop_threshold,
    )


def build_context_budget_snapshot(
    *,
    policy: dict,
    run_id: str | None,
    task: dict,
    runtime_context: dict,
    runtime_profile_id: str,
    context_mount_id: str,
    sequence: int = 1,
) -> ContextBudgetSnapshot:
    """Build a raw-content-free context attribution snapshot for Runtime gates."""

    sections = _runtime_context_sections(runtime_context)
    estimated_tokens = max(1, sum(sections.values()))
    pressure = context_pressure(policy, estimated_tokens)
    duplicate_hashes, duplicate_tokens, duplicate_refs = _duplicate_context_signals(
        runtime_context
    )
    worker_topology = runtime_context.get("worker_topology")
    worker_topology = worker_topology if isinstance(worker_topology, dict) else {}
    raw_context_mount = runtime_context.get("context_mount")
    context_mount: dict[str, Any] = raw_context_mount if isinstance(raw_context_mount, dict) else {}
    raw_includes = context_mount.get("includes")
    includes: dict[str, Any] = raw_includes if isinstance(raw_includes, dict) else {}
    isolation_policy = str(
        includes.get("isolation_policy")
        or _context_requirement(task, "isolation_policy")
        or "shared_task_context"
    )
    worker_kind = str(
        worker_topology.get("worker_kind") or _context_requirement(task, "worker_kind") or "primary"
    )
    scope = "subagent_child" if isolation_policy == "subagent_child_context" else "task_context"
    return ContextBudgetSnapshot(
        snapshot_id=f"context-budget-snapshot-{max(1, sequence):04d}",
        run_id=run_id,
        task_id=str(task.get("task_id") or ""),
        created_at=now_iso(),
        scope=scope,
        runtime_profile_id=runtime_profile_id,
        context_mount_id=context_mount_id,
        worker_kind=worker_kind,
        isolation_policy=isolation_policy,
        parent_worker_invocation_id=_string_or_none(
            worker_topology.get("parent_worker_invocation_id")
            or includes.get("parent_worker_invocation_id")
        ),
        parent_runtime_profile_id=_string_or_none(
            worker_topology.get("parent_runtime_profile_id")
            or includes.get("parent_runtime_profile_id")
        ),
        estimated_tokens=estimated_tokens,
        sections=sections,
        duplicate_content_hashes=duplicate_hashes,
        duplicate_estimated_tokens=duplicate_tokens,
        duplicate_ref_count=duplicate_refs,
        context_window_tokens=pressure.window_tokens,
        context_window_ratio=pressure.ratio,
        pressure_status=pressure.status,
        compaction_threshold=pressure.compaction_threshold,
        hard_stop_threshold=pressure.hard_stop_threshold,
        compact_boundary=_compact_boundary(pressure, sections, duplicate_tokens),
        evidence_refs=_context_evidence_refs(runtime_context),
    )


def record_context_budget_snapshot(
    *,
    run_dir: Path | None,
    validator: SchemaValidator,
    policy: dict,
    run_id: str | None,
    task: dict,
    runtime_context: dict,
    runtime_profile_id: str,
    context_mount_id: str,
) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    path = run_dir / "context_budget_snapshots.jsonl"
    store = JsonlStore(validator)
    existing = store.read_all(path, "context_budget_snapshot") if path.exists() else []
    snapshot = build_context_budget_snapshot(
        policy=policy,
        run_id=run_id,
        task=task,
        runtime_context=runtime_context,
        runtime_profile_id=runtime_profile_id,
        context_mount_id=context_mount_id,
        sequence=len(existing) + 1,
    ).to_dict()
    store.append(path, snapshot, "context_budget_snapshot")
    return snapshot


def _section_for_message(message: Any, content: str, metadata: dict[str, Any]) -> str:
    role = str(getattr(message, "role", "") or "").lower()
    lowered = content.lower()
    if role == "system":
        return "prompt_envelope" if metadata.get("prompt_envelope_hash") else "system_prompt"
    if metadata.get("context_envelope_hash") and (
        "context_envelope" in lowered or "active_goal_memory" in lowered
    ):
        return "context_envelope"
    if "tool_observation" in lowered or "tool_output" in lowered or "tool_calls" in lowered:
        return "tool_output"
    if "active_goal" in lowered or "memory" in lowered or "contextsnapshot" in lowered:
        return "memory"
    if "file" in lowered and ("path" in lowered or "content" in lowered or "excerpt" in lowered):
        return "file_excerpts"
    return "conversation"


def _runtime_context_sections(runtime_context: dict) -> dict[str, int]:
    sections: dict[str, int] = {}
    package = runtime_context.get("context_package")
    package = package if isinstance(package, dict) else {}
    package_sections = [
        "root_guidance",
        "goal_brief",
        "task_brief",
        "read_scope_files",
        "write_scope_files",
        "evidence_scope",
        "artifacts",
        "failures",
        "recent_failures",
        "decisions",
        "validations",
        "runtime_requests",
        "worker_results",
        "merge_gate_evidence",
        "recent_events",
        "context_envelope",
    ]
    for name in package_sections:
        if name in package and package.get(name):
            tokens = estimate_text_tokens(_stable_json(package.get(name)))
            if tokens > 0:
                sections[name] = tokens
    top_level = {
        "context_mount": runtime_context.get("context_mount"),
        "task_contract": runtime_context.get("task_contract"),
        "agent_loop_profile": runtime_context.get("agent_loop_profile"),
        "capability_registry": runtime_context.get("capability_registry"),
        "route_guidance": runtime_context.get("route_guidance"),
        "agent_role_contract": runtime_context.get("agent_role_contract"),
        "worker_topology": runtime_context.get("worker_topology"),
        "subagent_worker": runtime_context.get("subagent_worker"),
        "parent_agent_loop_decision": runtime_context.get("parent_agent_loop_decision"),
        "parent_agent_loop_execution": runtime_context.get("parent_agent_loop_execution"),
        "latest_agent_loop_observation": runtime_context.get("latest_agent_loop_observation"),
        "agent_loop_round": runtime_context.get("agent_loop_round"),
    }
    for name, value in top_level.items():
        if value:
            tokens = estimate_text_tokens(_stable_json(value))
            if tokens > 0:
                sections[name] = sections.get(name, 0) + tokens
    return {key: value for key, value in sections.items() if value > 0}


def _duplicate_context_signals(value: Any) -> tuple[list[str], int, int]:
    seen: dict[str, tuple[int, int]] = {}
    for text in _iter_context_strings(value):
        digest = _content_hash(text)
        if not digest:
            continue
        count, tokens = seen.get(digest, (0, estimate_text_tokens(text)))
        seen[digest] = (count + 1, tokens)
    duplicate_hashes = sorted(hash_ for hash_, (count, _) in seen.items() if count > 1)
    duplicate_tokens = sum((count - 1) * tokens for count, tokens in seen.values() if count > 1)
    duplicate_refs = sum(count - 1 for count, _ in seen.values() if count > 1)
    return duplicate_hashes[:20], duplicate_tokens, duplicate_refs


def _iter_context_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if len(" ".join(value.split())) >= 64:
            yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_context_strings(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_context_strings(item)


def _compact_boundary(
    pressure: ContextPressure,
    sections: dict[str, int],
    duplicate_tokens: int,
) -> dict[str, Any]:
    if pressure.status in {"hard_stop", "exceeded"}:
        status = "required"
        recommended_action = "compact_before_next_child_round"
    elif pressure.status == "near_limit":
        status = "recommended"
        recommended_action = "compact_or_narrow_child_context"
    elif duplicate_tokens >= max(2000, int(pressure.estimated_tokens * 0.2)):
        status = "dedupe_recommended"
        recommended_action = "dedupe_repeated_child_context"
    else:
        status = "not_required"
        recommended_action = "continue"
    preserve = [
        name
        for name in (
            "goal_brief",
            "task_brief",
            "failures",
            "recent_failures",
            "validations",
            "worker_results",
            "parent_agent_loop_decision",
            "parent_agent_loop_execution",
            "latest_agent_loop_observation",
        )
        if name in sections
    ]
    droppable = [
        name
        for name in (
            "read_scope_files",
            "artifacts",
            "recent_events",
            "context_envelope",
            "capability_registry",
        )
        if name in sections
    ]
    return {
        "status": status,
        "recommended_action": recommended_action,
        "estimated_tokens_before": pressure.estimated_tokens,
        "estimated_duplicate_tokens": duplicate_tokens,
        "preserve_sections": preserve,
        "droppable_sections": droppable,
    }


def _context_evidence_refs(runtime_context: dict) -> list[str]:
    refs: list[str] = []
    package = runtime_context.get("context_package")
    package = package if isinstance(package, dict) else {}
    for key in ("context_envelope_path",):
        value = package.get(key)
        if value:
            refs.append(str(value))
    mount = runtime_context.get("context_mount")
    mount = mount if isinstance(mount, dict) else {}
    if mount.get("context_mount_id"):
        refs.append(str(mount["context_mount_id"]))
    for key in ("runtime_profile_id", "model_profile_id", "tool_permission_profile_id"):
        value = runtime_context.get(key)
        if value:
            refs.append(str(value))
    return list(dict.fromkeys(refs))


def _context_requirement(task: dict, key: str) -> str | None:
    requirements = task.get("context_requirements")
    if isinstance(requirements, dict) and requirements.get(key):
        return str(requirements[key])
    hints = task.get("runtime_profile_hints")
    if isinstance(hints, dict) and hints.get(key):
        return str(hints[key])
    value = task.get(key)
    return str(value) if value else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value else None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return str(value)


def _content_hash(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) < 64:
        return ""
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]
