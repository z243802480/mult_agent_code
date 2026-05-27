from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.context_envelope import ContextEnvelope
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import read_scope, write_scope
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class ContextPackageBuilder:
    validator: SchemaValidator
    max_file_chars: int = 4_000
    max_scope_files: int = 12

    def build(self, context: RuntimeContext, task: dict, context_mount: dict) -> dict:
        includes = context_mount.get("includes") if isinstance(context_mount, dict) else {}
        if not isinstance(includes, dict):
            includes = {}
        read_scope_files = self._read_scope_files(context, task)
        artifacts = self._artifacts(context, includes.get("artifact_refs", []))
        failures = self._failures(context, includes.get("failure_evidence_refs", []))
        decisions = self._decisions(context, includes.get("decision_refs", []))
        validations = self._validations(context, includes.get("validation_refs", []))
        runtime_requests = self._runtime_requests(context, task["task_id"])
        worker_results = self._worker_results(context, task["task_id"])
        merge_gate_evidence = self._merge_gate_evidence(context, task["task_id"])
        recent_failures = self._recent_failures(context, task["task_id"])
        package = {
            "package_id": f"context-package-{task['task_id']}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "mount_type": context_mount.get("mount_type") if isinstance(context_mount, dict) else None,
            "scope_summary": self._scope_summary(
                task,
                read_scope_files=read_scope_files,
                artifacts=artifacts,
                failures=failures,
                decisions=decisions,
                validations=validations,
                runtime_requests=runtime_requests,
                worker_results=worker_results,
                merge_gate_evidence=merge_gate_evidence,
                recent_failures=recent_failures,
            ),
            "root_guidance": self._root_guidance(context) if includes.get("root_guidance") else {},
            "goal_brief": self._goal_brief(context) if includes.get("goal_brief") else {},
            "task_brief": self._task_brief(task) if includes.get("task_brief") else {},
            "read_scope_files": read_scope_files,
            "write_scope_files": self._write_scope_files(context, task),
            "evidence_scope": self._evidence_scope(
                includes,
                artifacts=artifacts,
                failures=failures,
                decisions=decisions,
                validations=validations,
            ),
            "artifacts": artifacts,
            "failures": failures,
            "recent_failures": recent_failures,
            "decisions": decisions,
            "validations": validations,
            "runtime_requests": runtime_requests,
            "worker_results": worker_results,
            "merge_gate_evidence": merge_gate_evidence,
            "recent_events": self._recent_events(context, int(includes.get("recent_event_count") or 0)),
        }
        context_envelope = ContextEnvelope.from_payload(
            audience="worker",
            mode="context_package",
            intent=str(package.get("mount_type") or "worker_context"),
            root=context.root,
            run_id=context.run_id,
            refs=self._context_envelope_refs(package),
            payload=deepcopy(package),
            sections=self._context_envelope_sections(package),
            redaction_policy={
                "backend_fields_allowed": True,
                "protected_terms": ["secret", "token", "api_key", "password", "credential"],
            },
        )
        package["context_envelope"] = context_envelope.to_dict()
        envelope_path = self._persist_context_envelope(context, task["task_id"], context_envelope)
        if envelope_path is not None:
            package["context_envelope_path"] = envelope_path.relative_to(context.root).as_posix()
        return package

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

    def _validations(self, context: RuntimeContext, refs: object) -> list[dict]:
        if context.run_dir is None or not isinstance(refs, list):
            return []
        validations = self._items_by_id(
            context.run_dir / "validation_results.jsonl",
            "validation_result",
            "validation_result_id",
        )
        return [
            {
                "validation_result_id": validations[ref].get("validation_result_id"),
                "task_id": validations[ref].get("task_id"),
                "tool_name": validations[ref].get("tool_name"),
                "command": validations[ref].get("command"),
                "status": validations[ref].get("status"),
                "summary": validations[ref].get("summary"),
                "error": validations[ref].get("error"),
            }
            for ref in refs
            if isinstance(ref, str) and ref in validations
        ]

    def _read_scope_files(self, context: RuntimeContext, task: dict) -> list[dict]:
        files: list[dict] = []
        seen: set[str] = set()
        for scope_item in read_scope(task):
            for path in self._scope_paths(context, scope_item):
                rel = path.relative_to(context.root).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                files.append(
                    {
                        "path": rel,
                        "content": self._workspace_file_content(context, rel),
                    }
                )
                if len(files) >= self.max_scope_files:
                    return files
        return files

    def _write_scope_files(self, context: RuntimeContext, task: dict) -> list[dict]:
        files: list[dict] = []
        for scope_item in write_scope(task)[: self.max_scope_files]:
            try:
                resolved = PathGuard(context.root, context.policy["protected_paths"]).resolve_for_read(
                    scope_item
                )
                exists = resolved.exists()
            except (OSError, PermissionError):
                exists = False
            files.append({"path": scope_item, "exists": exists})
        return files

    def _evidence_scope(
        self,
        includes: dict,
        *,
        artifacts: list[dict],
        failures: list[dict],
        decisions: list[dict],
        validations: list[dict],
    ) -> dict:
        return {
            "requested_refs": {
                "artifacts": self._string_refs(includes.get("artifact_refs", [])),
                "failures": self._string_refs(includes.get("failure_evidence_refs", [])),
                "decisions": self._string_refs(includes.get("decision_refs", [])),
                "validations": self._string_refs(includes.get("validation_refs", [])),
            },
            "included_counts": {
                "artifacts": len(artifacts),
                "failures": len(failures),
                "decisions": len(decisions),
                "validations": len(validations),
            },
        }

    def _scope_summary(
        self,
        task: dict,
        *,
        read_scope_files: list[dict],
        artifacts: list[dict],
        failures: list[dict],
        decisions: list[dict],
        validations: list[dict],
        runtime_requests: list[dict],
        worker_results: list[dict],
        merge_gate_evidence: list[dict],
        recent_failures: list[dict],
    ) -> dict:
        return {
            "read_scope": read_scope(task),
            "read_scope_file_count": len(read_scope_files),
            "write_scope": write_scope(task),
            "evidence_counts": {
                "artifacts": len(artifacts),
                "failures": len(failures),
                "decisions": len(decisions),
                "validations": len(validations),
                "runtime_requests": len(runtime_requests),
                "worker_results": len(worker_results),
                "merge_gate_evidence": len(merge_gate_evidence),
                "recent_failures": len(recent_failures),
            },
        }

    def _scope_paths(self, context: RuntimeContext, scope_item: str) -> list[Path]:
        try:
            resolved = PathGuard(context.root, context.policy["protected_paths"]).resolve_for_read(
                scope_item
            )
        except (OSError, PermissionError):
            return []
        if resolved.is_file():
            return [resolved]
        if not resolved.exists() or not resolved.is_dir():
            return []
        paths: list[Path] = []
        for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix()):
            if len(paths) >= self.max_scope_files:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(context.root).as_posix()
            try:
                PathGuard(context.root, context.policy["protected_paths"]).resolve_for_read(rel)
            except (OSError, PermissionError):
                continue
            paths.append(path)
        return paths

    def _runtime_requests(self, context: RuntimeContext, task_id: str) -> list[dict]:
        if context.run_dir is None:
            return []
        requests = self._items_by_task(
            context.run_dir / "runtime_requests.jsonl",
            "runtime_request",
            task_id,
        )
        return [
            {
                "runtime_request_id": item.get("runtime_request_id"),
                "request_type": item.get("request_type"),
                "risk": item.get("risk"),
                "status": item.get("status"),
                "decision_id": item.get("decision_id"),
                "reason": item.get("reason"),
                "details": item.get("details", {}),
            }
            for item in requests[-5:]
        ]

    def _worker_results(self, context: RuntimeContext, task_id: str) -> list[dict]:
        if context.run_dir is None:
            return []
        workers = {
            item["worker_invocation_id"]: item
            for item in self._items_by_task(
                context.run_dir / "workers.jsonl",
                "worker_invocation",
                task_id,
            )
            if item.get("worker_invocation_id")
        }
        results = self._items_by_task(
            context.run_dir / "worker_results.jsonl",
            "worker_result",
            task_id,
        )
        return [
            {
                "worker_invocation_id": item.get("worker_invocation_id"),
                "runtime_profile_id": workers.get(item.get("worker_invocation_id"), {}).get(
                    "runtime_profile_id"
                ),
                "status": item.get("status"),
                "artifact_refs": item.get("artifact_refs", []),
                "validation_refs": item.get("validation_refs", []),
                "failure_evidence_refs": item.get("failure_evidence_refs", []),
                "summary": item.get("summary"),
            }
            for item in results[-5:]
        ]

    def _merge_gate_evidence(self, context: RuntimeContext, task_id: str) -> list[dict]:
        if context.run_dir is None:
            return []
        evidence = self._items_by_task(
            context.run_dir / "task_execution_evidence.jsonl",
            "task_execution_evidence",
            task_id,
        )
        items = []
        for item in evidence:
            contract = item.get("contract_check")
            contract = contract if isinstance(contract, dict) else {}
            merge_gate = contract.get("merge_gate")
            if not isinstance(merge_gate, dict):
                continue
            items.append(
                {
                    "evidence_id": item.get("evidence_id"),
                    "status": item.get("status"),
                    "summary": item.get("summary"),
                    "merge_gate": merge_gate,
                }
            )
        return items[-5:]

    def _recent_failures(self, context: RuntimeContext, task_id: str) -> list[dict]:
        if context.run_dir is None:
            return []
        failures = self._items_by_task(
            context.run_dir / "task_failures.jsonl",
            "task_failure_evidence",
            task_id,
        )
        return [
            {
                "evidence_id": item.get("evidence_id"),
                "phase": item.get("phase"),
                "failure_type": item.get("failure_type"),
                "summary": item.get("summary"),
                "created_at": item.get("created_at"),
            }
            for item in failures[-3:]
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

    def _items_by_task(self, path: Path, schema_name: str, task_id: str) -> list[dict]:
        if not path.exists():
            return []
        return [
            item
            for item in JsonlStore(self.validator).read_all(path, schema_name)
            if item.get("task_id") == task_id
        ]

    def _string_refs(self, refs: object) -> list[str]:
        if not isinstance(refs, list):
            return []
        return [item for item in refs if isinstance(item, str)]

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

    def _context_envelope_refs(self, package: dict) -> list[str]:
        refs: list[str] = []
        for item in package.get("read_scope_files") or []:
            if isinstance(item, dict) and item.get("path"):
                refs.append(str(item["path"]))
        for group in ("artifacts", "failures", "decisions", "validations"):
            for item in package.get(group) or []:
                if isinstance(item, dict):
                    identifier = (
                        item.get("artifact_id")
                        or item.get("evidence_id")
                        or item.get("decision_id")
                        or item.get("validation_result_id")
                    )
                    if identifier:
                        refs.append(str(identifier))
        return refs

    def _persist_context_envelope(
        self,
        context: RuntimeContext,
        task_id: str,
        envelope: ContextEnvelope,
    ) -> Path | None:
        if context.run_dir is None:
            return None
        path = context.run_dir / "context_envelopes" / f"context_envelope_{task_id}.json"
        JsonStore(self.validator).write(path, envelope.to_dict(), "context_envelope")
        return path

    def _context_envelope_sections(self, package: dict) -> list[dict]:
        section_names = [
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
        ]
        sections = []
        for name in section_names:
            value = package.get(name)
            included = bool(value)
            sections.append(
                {
                    "name": name,
                    "included": included,
                    "summary": self._section_summary(value) if included else "not mounted",
                }
            )
        return sections

    def _section_summary(self, value: object) -> str:
        if isinstance(value, dict):
            return f"{len(value)} field(s)"
        if isinstance(value, list):
            return f"{len(value)} item(s)"
        return "mounted"
