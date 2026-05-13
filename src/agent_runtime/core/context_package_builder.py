from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.path_guard import PathGuard
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class ContextPackageBuilder:
    validator: SchemaValidator
    max_file_chars: int = 4_000

    def build(self, context: RuntimeContext, task: dict, context_mount: dict) -> dict:
        includes = context_mount.get("includes") if isinstance(context_mount, dict) else {}
        if not isinstance(includes, dict):
            includes = {}
        return {
            "package_id": f"context-package-{task['task_id']}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "mount_type": context_mount.get("mount_type") if isinstance(context_mount, dict) else None,
            "root_guidance": self._root_guidance(context) if includes.get("root_guidance") else {},
            "goal_brief": self._goal_brief(context) if includes.get("goal_brief") else {},
            "task_brief": self._task_brief(task) if includes.get("task_brief") else {},
            "artifacts": self._artifacts(context, includes.get("artifact_refs", [])),
            "failures": self._failures(context, includes.get("failure_evidence_refs", [])),
            "decisions": self._decisions(context, includes.get("decision_refs", [])),
            "recent_events": self._recent_events(context, int(includes.get("recent_event_count") or 0)),
        }

    def _root_guidance(self, context: RuntimeContext) -> dict:
        path = context.root / "AGENTS.md"
        if not path.exists():
            return {}
        return {
            "path": "AGENTS.md",
            "content": path.read_text(encoding="utf-8")[: self.max_file_chars],
        }

    def _goal_brief(self, context: RuntimeContext) -> dict:
        if context.run_dir is None:
            return {}
        path = context.run_dir / "goal_spec.json"
        if not path.exists():
            return {}
        goal = JsonStore(self.validator).read(path, "goal_spec")
        return {
            "goal_id": goal.get("goal_id"),
            "normalized_goal": goal.get("normalized_goal"),
            "definition_of_done": goal.get("definition_of_done", [])[:5],
            "constraints": goal.get("constraints", [])[:5],
        }

    def _task_brief(self, task: dict) -> dict:
        return {
            "task_id": task.get("task_id"),
            "title": task.get("title"),
            "description": task.get("description"),
            "acceptance": task.get("acceptance", [])[:5],
            "task_kind": task.get("task_kind"),
            "parallel_safety": task.get("parallel_safety"),
            "read_scope": task.get("read_scope", []),
            "write_scope": task.get("write_scope", []),
        }

    def _artifacts(self, context: RuntimeContext, refs: object) -> list[dict]:
        if context.run_dir is None or not isinstance(refs, list):
            return []
        artifacts = self._items_by_id(context.run_dir / "artifacts.jsonl", "artifact", "artifact_id")
        return [
            self._artifact_slice(context, artifacts[ref])
            for ref in refs
            if isinstance(ref, str) and ref in artifacts
        ]

    def _artifact_slice(self, context: RuntimeContext, artifact: dict) -> dict:
        item = {
            "artifact_id": artifact.get("artifact_id"),
            "task_id": artifact.get("task_id"),
            "type": artifact.get("type"),
            "path": artifact.get("path"),
            "summary": artifact.get("summary"),
        }
        path = str(artifact.get("path") or "")
        if path:
            item["content"] = self._workspace_file_content(context, path)
        return item

    def _failures(self, context: RuntimeContext, refs: object) -> list[dict]:
        if context.run_dir is None or not isinstance(refs, list):
            return []
        failures = self._items_by_id(
            context.run_dir / "task_failures.jsonl",
            "task_failure_evidence",
            "evidence_id",
        )
        return [
            {
                "evidence_id": failures[ref].get("evidence_id"),
                "task_id": failures[ref].get("task_id"),
                "phase": failures[ref].get("phase"),
                "failure_type": failures[ref].get("failure_type"),
                "summary": failures[ref].get("summary"),
                "contract_check": failures[ref].get("contract_check", {}),
                "recommendations": failures[ref].get("recommendations", [])[:5],
            }
            for ref in refs
            if isinstance(ref, str) and ref in failures
        ]

    def _decisions(self, context: RuntimeContext, refs: object) -> list[dict]:
        if context.run_dir is None or not isinstance(refs, list):
            return []
        decisions = self._items_by_id(context.run_dir / "decisions.jsonl", "decision_point", "decision_id")
        return [
            {
                "decision_id": decisions[ref].get("decision_id"),
                "status": decisions[ref].get("status"),
                "question": decisions[ref].get("question"),
                "selected_option_id": decisions[ref].get("selected_option_id"),
                "metadata": decisions[ref].get("metadata", {}),
            }
            for ref in refs
            if isinstance(ref, str) and ref in decisions
        ]

    def _recent_events(self, context: RuntimeContext, limit: int) -> list[dict]:
        if context.run_dir is None or limit <= 0:
            return []
        path = context.run_dir / "events.jsonl"
        if not path.exists():
            return []
        events = JsonlStore(self.validator).read_all(path, "event")
        return [
            {
                "event_id": item.get("event_id"),
                "type": item.get("type"),
                "actor": item.get("actor"),
                "summary": item.get("summary"),
                "created_at": item.get("created_at"),
            }
            for item in events[-limit:]
        ]

    def _items_by_id(self, path: Path, schema_name: str, id_key: str) -> dict[str, dict]:
        if not path.exists():
            return {}
        return {
            str(item[id_key]): item
            for item in JsonlStore(self.validator).read_all(path, schema_name)
            if item.get(id_key)
        }

    def _workspace_file_content(self, context: RuntimeContext, path: str) -> dict:
        try:
            resolved = PathGuard(context.root, context.policy["protected_paths"]).resolve_for_read(path)
            if not resolved.exists() or not resolved.is_file():
                return {"omitted": "missing"}
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"omitted": "non_utf8"}
        except (OSError, PermissionError):
            return {"omitted": "unreadable"}
        return {
            "text": content[: self.max_file_chars],
            "truncated": len(content) > self.max_file_chars,
        }
