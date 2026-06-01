from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


RECOVERY_CHAINS = [
    "resume",
    "replan",
    "repair",
    "damaged_memory",
    "multi_run_conflict",
    "permission_block",
    "compact_continuation",
]


def recovery_pressure_report(root: Path, validator: SchemaValidator) -> dict[str, Any]:
    store = JsonlStore(validator)
    run_dirs = _run_dirs(root)
    evidence = _scan_runs(run_dirs, store)
    evidence["damaged_memory"] = _damaged_memory_evidence(root)
    evidence["multi_run_conflict"].extend(_multi_run_conflict_evidence(root))
    evidence["compact_continuation"].extend(_compact_continuation_evidence(root))
    chains = {
        name: {
            "covered": bool(items),
            "evidence_count": len(items),
            "sample_refs": items[:5],
        }
        for name, items in evidence.items()
    }
    covered = len([name for name, chain in chains.items() if chain["covered"]])
    return {
        "schema_version": "0.1.0",
        "run_count": len(run_dirs),
        "required_chains": RECOVERY_CHAINS,
        "covered": covered,
        "missing": [name for name, chain in chains.items() if not chain["covered"]],
        "coverage_ratio": _ratio(covered, len(RECOVERY_CHAINS)),
        "ready": covered == len(RECOVERY_CHAINS),
        "chains": chains,
    }


def recovery_pressure_text_lines(report: dict[str, Any]) -> list[str]:
    if not report:
        return []
    return [
        "Recovery pressure: "
        f"{report.get('covered', 0)}/{len(report.get('required_chains') or [])} chains "
        f"ready={report.get('ready', False)}"
    ]


def _scan_runs(run_dirs: list[Path], store: JsonlStore) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {name: [] for name in RECOVERY_CHAINS}
    for run_dir in run_dirs:
        progress = _read_jsonl(store, run_dir / "user_progress.jsonl", "user_progress_event")
        decisions = _read_jsonl(store, run_dir / "decisions.jsonl", None)
        requests = _read_jsonl(store, run_dir / "runtime_requests.jsonl", None)
        failures = _read_jsonl(store, run_dir / "task_failures.jsonl", None)
        task_plan = _read_json(run_dir / "task_plan.json")
        for event in progress:
            haystack = _event_text(event)
            if "resume" in haystack:
                evidence["resume"].append(f"{run_dir.name}/user_progress.jsonl")
            if "replan" in haystack:
                evidence["replan"].append(f"{run_dir.name}/user_progress.jsonl")
            if "repair" in haystack:
                evidence["repair"].append(f"{run_dir.name}/user_progress.jsonl")
            if event.get("event_type") in {"permission_request", "permission_decision"}:
                evidence["permission_block"].append(f"{run_dir.name}/user_progress.jsonl")
            if "context_compacted" in haystack or "compact" in haystack:
                evidence["compact_continuation"].append(f"{run_dir.name}/user_progress.jsonl")
        for event in _read_jsonl(store, run_dir / "events.jsonl", "event"):
            if event.get("type") == "context_compacted" or "context_compacted" in _event_text(event):
                evidence["compact_continuation"].append(f"{run_dir.name}/events.jsonl")
        for decision in decisions:
            raw_metadata = decision.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            text = _event_text(decision)
            if metadata.get("kind") == "replan_decision" or "replan" in text:
                evidence["replan"].append(f"{run_dir.name}/decisions.jsonl")
            if metadata.get("kind") == "execution_policy_approval":
                evidence["permission_block"].append(f"{run_dir.name}/decisions.jsonl")
        for request in requests:
            text = _event_text(request)
            if "permission" in text or "approval" in text:
                evidence["permission_block"].append(f"{run_dir.name}/runtime_requests.jsonl")
        for failure in failures:
            text = _event_text(failure)
            if "repair" in text or "verification" in text:
                evidence["repair"].append(f"{run_dir.name}/task_failures.jsonl")
        if _task_plan_has_repair(task_plan):
            evidence["repair"].append(f"{run_dir.name}/task_plan.json")
        if _task_plan_has_replan(task_plan):
            evidence["replan"].append(f"{run_dir.name}/task_plan.json")
    return {name: sorted(set(items)) for name, items in evidence.items()}


def _damaged_memory_evidence(root: Path) -> list[str]:
    recovery_events = _memory_recovery_events(root)
    damaged = [
        ".asteria/memory/recovery_events.jsonl"
        for item in recovery_events
        if str(item.get("chain") or "") == "damaged_memory"
    ]
    damaged.extend(_invalid_memory_jsonl_evidence(root))
    if damaged:
        return sorted(set(damaged))
    memory = _read_json(root / ".asteria" / "memory" / "active_goal.json")
    if str(memory.get("update_reason") or "") == "recovery_from_corrupt_json":
        return [".asteria/memory/active_goal.json"]
    haystack = _event_text(memory)
    if "corrupt" in haystack or "damaged" in haystack or "损坏" in haystack:
        return [".asteria/memory/active_goal.json"]
    return []


def _invalid_memory_jsonl_evidence(root: Path) -> list[str]:
    memory_dir = root / ".asteria" / "memory"
    if not memory_dir.exists():
        return []
    refs: list[str] = []
    for path in sorted(memory_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                refs.append(f".asteria/memory/{path.name}")
                break
            if not isinstance(item, dict) or not _looks_like_memory_entry(item):
                refs.append(f".asteria/memory/{path.name}")
                break
    return sorted(set(refs))


def _looks_like_memory_entry(item: dict[str, Any]) -> bool:
    required = {"memory_id", "type", "content", "source", "tags", "confidence", "created_at"}
    return required <= set(item)


def _multi_run_conflict_evidence(root: Path) -> list[str]:
    recovery_events = _memory_recovery_events(root)
    conflict = [
        ".asteria/memory/recovery_events.jsonl"
        for item in recovery_events
        if str(item.get("chain") or "") == "multi_run_conflict"
    ]
    if conflict:
        return sorted(set(conflict))
    memory = _read_json(root / ".asteria" / "memory" / "active_goal.json")
    haystack = _event_text(memory)
    if "conflict" in haystack or "another unfinished run" in haystack or "冲突" in haystack:
        return [".asteria/memory/active_goal.json"]
    return []


def _compact_continuation_evidence(root: Path) -> list[str]:
    refs: list[str] = []
    snapshots_dir = root / ".asteria" / "context" / "snapshots"
    if snapshots_dir.exists():
        for path in sorted(snapshots_dir.glob("*.json")):
            snapshot = _read_json(path)
            if snapshot.get("compaction_purpose") or snapshot.get("next_actions"):
                refs.append(f".asteria/context/snapshots/{path.name}")
    return refs


def _memory_recovery_events(root: Path) -> list[dict[str, Any]]:
    path = root / ".asteria" / "memory" / "recovery_events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
    except (OSError, ValueError):
        return []
    return events


def _read_jsonl(store: JsonlStore, path: Path, schema_name: str | None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return store.read_all(path, schema_name)
    except (OSError, ValueError):
        return []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _task_plan_has_repair(task_plan: dict[str, Any]) -> bool:
    raw_tasks = task_plan.get("tasks")
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    for task in tasks:
        text = _event_text(task)
        policy = task.get("failure_policy") if isinstance(task, dict) else None
        if "repair" in text or policy == "create_repair_task":
            return True
    return False


def _task_plan_has_replan(task_plan: dict[str, Any]) -> bool:
    raw_tasks = task_plan.get("tasks")
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    return any("replan" in _event_text(task) for task in tasks)


def _event_text(item: Any) -> str:
    try:
        return json.dumps(item, ensure_ascii=False, sort_keys=True).lower()
    except (TypeError, ValueError):
        return str(item).lower()


def _run_dirs(root: Path) -> list[Path]:
    runs_dir = root / ".asteria" / "runs"
    return [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
