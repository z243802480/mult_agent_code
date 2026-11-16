"""Scoped evidence snapshots and on-demand history; no semantic coverage inference."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.tools.base import ToolResult

MAX_SECTION_CHARS = 262_144
MAX_SNAPSHOT_CHARS = 1_048_576
MAX_INDEX_ROWS = 64
INLINE_SECTION_CHARS = 8_000
INLINE_HISTORY_CHARS = 24_000


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def verification_origins(run_id: str | None, board: dict, observations: list[dict], calls: list[dict]) -> dict:
    """Report recorded attribution and exact method membership, never infer a chooser/coverage."""
    joined: dict[str, list[dict]] = {}
    for call in calls:
        if call.get("run_id") == run_id:
            joined.setdefault(str(call.get("tool_call_id")), []).append(call)
    tasks = {t["task_id"]: t for t in board.get("tasks", []) if t.get("task_id")}
    rows = []
    for row in observations:
        if row.get("run_id") != run_id or row.get("tool_name") not in {"run_command", "run_tests", "run_pytest"}:
            continue
        data = (row.get("observation") or {}).get("data") or {}
        command = data.get("requested_command") or data.get("command")
        command = command if isinstance(command, str) else ""
        candidates = joined.get(str(row.get("tool_call_id")), [])
        call = candidates[0] if (len(candidates) == 1 and candidates[0].get("task_id") == row.get("task_id")
                                and candidates[0].get("tool_name") == row.get("tool_name")) else {}
        task = tasks.get(row.get("task_id"), {})
        relation = "unregistered_or_unknown"
        if command and command in task.get("validation_commands", []):
            relation = "current_declared_task_method"
        elif command and any(command == h.get("original_command") for h in
                             (task.get("verification_policy") or {}).get("method_revisions", [])):
            relation = "recorded_replaced_method"
        rows.append({"tool_call_id": row.get("tool_call_id"), "observation_id": row.get("observation_id"),
                     "task_id": row.get("task_id"), "recorded_executor": call.get("agent_id") or "unknown",
                     "selection_origin": "not_recorded", "method_relation": relation,
                     "task_discarded": task.get("status") == "discarded", "ok": row.get("ok"),
                     "returncode": data.get("returncode") if type(data.get("returncode")) is int else None,
                     "command_excerpt": command[:240], "command_truncated": len(command) > 240,
                     "command_sha256": hashlib.sha256(command.encode("utf8")).hexdigest() if command else None,
                     "artifact_binding": "historical_execution_not_bound_to_this_review_snapshot",
                     "requirement_coverage": "unassessed"})
    return {"temporal_scope": "before_current_review", "record_count": len(rows),
            "executor_counts": dict(Counter(r["recorded_executor"] for r in rows)),
            "records": rows[-MAX_INDEX_ROWS:], "omitted_records": max(0, len(rows) - MAX_INDEX_ROWS),
            "current_review_checks_at_start": 0, "requirement_coverage": "unassessed",
            "independent_method_design": "not_established_by_executor_or_exit_code",
            "same_task_relation_establishes_criterion_coverage": False}


class ReviewEvidence:
    """Only previously authorized Review context, frozen in memory and schema-persisted."""

    name = "inspect_evidence"

    def __init__(self, context: RuntimeContext, snapshot_id: str, task_id: str,
                 review_context: dict, observations: list[dict], calls: list[dict], board: dict) -> None:
        self.context, self.snapshot_id, self.task_id = context, snapshot_id, task_id
        self.sections: dict[str, dict] = {}
        self.remaining = MAX_SNAPSHOT_CHARS
        self.origins = verification_origins(context.run_id, board, observations, calls)
        counts = Counter(r.get("tool_call_id") for r in observations if r.get("run_id") == context.run_id)
        for row in observations[-MAX_INDEX_ROWS:]:
            if row.get("run_id") == context.run_id and counts[row.get("tool_call_id")] == 1:
                ref = self._freeze("observation/" + str(row["tool_call_id"]), row)
                for origin in self.origins["records"]:
                    if origin["tool_call_id"] == row["tool_call_id"]:
                        origin["evidence_ref"] = ref
        self.view = deepcopy(review_context)
        history_remaining = INLINE_HISTORY_CHARS

        def project(container: dict, key: str, path: str) -> None:
            nonlocal history_remaining
            if key not in container:
                return
            text = _json(container[key])
            reference = self._freeze(path, container[key])
            if len(text) > INLINE_SECTION_CHARS or len(text) > history_remaining:
                container[key] = {"deferred_evidence_ref": reference, "characters": len(text),
                                  "source": "historical_context_not_current_review_conclusion"}
            else:
                history_remaining -= len(text)

        trajectory = self.view.get("trajectory")
        if isinstance(trajectory, dict):
            for key in list(trajectory):
                if key in {"route_health", "model_selection"}:
                    continue
                value = trajectory[key]
                if key == "runtime_os_evidence" and isinstance(value, dict):
                    for child in list(value):
                        if child != "summary":
                            project(value, child, f"trajectory.{key}.{child}")
                else:
                    project(trajectory, key, f"trajectory.{key}")
        for key in ("tool_observations", "tool_observation_actions", "latest_observation_plan",
                    "collaboration_summary", "latest_real_provider_matrix"):
            project(self.view, key, key)
        self.view["review_evidence"] = {"verification_origins": self.origins, "catalog": self.catalog(),
                                        "source_snapshot_id": snapshot_id}
        self.path = context.run_dir / f"{snapshot_id}-evidence.json" if context.run_dir else None
        if self.path is not None:
            JsonStore(context.validator).write(self.path, {
                "schema_version": "0.1.0", "run_id": context.run_id, "task_id": task_id,
                "source_snapshot_id": snapshot_id, "sections": list(self.sections.values()),
                "verification_origins": self.origins,
            }, "review_evidence")

    def _freeze(self, key: str, value) -> str:
        ref = self.snapshot_id + "/" + key
        if ref not in self.sections:
            content = _json(value)
            shown = content[:min(MAX_SECTION_CHARS, self.remaining)]
            self.remaining -= len(shown)
            self.sections[ref] = {"evidence_ref": ref, "content": shown, "characters": len(content),
                                  "stored_characters": len(shown), "truncated": shown != content,
                                  "content_sha256": hashlib.sha256(content.encode("utf8")).hexdigest()}
        return ref

    def catalog(self) -> list[dict]:
        return [{k: v for k, v in s.items() if k != "content"} for s in self.sections.values()
                if "/observation/" not in s["evidence_ref"]]

    def input_view(self) -> dict:
        return deepcopy(self.view)

    def run(self, context: RuntimeContext, evidence_ref: str, offset: int = 0, limit: int = 4000) -> ToolResult:
        if (context.run_id != self.context.run_id or context.run_dir != self.context.run_dir
                or context.task_id != self.task_id):
            raise PermissionError("Evidence is scoped to this Review session and task")
        if not isinstance(evidence_ref, str) or evidence_ref not in self.sections:
            raise PermissionError("Unknown evidence reference; paths and other runs are not accessible")
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4000):
            raise ValueError("Use a nonnegative offset and a page limit from 1 to 4000")
        section = self.sections[evidence_ref]
        content = section["content"][offset:offset + limit]
        end = offset + len(content)
        return ToolResult(ok=True, summary=f"Read scoped evidence {evidence_ref}", data={
            **{k: v for k, v in section.items() if k != "content"}, "content": content, "offset": offset,
            "next_offset": end if end < section["stored_characters"] else None,
            "source_snapshot_id": self.snapshot_id})
