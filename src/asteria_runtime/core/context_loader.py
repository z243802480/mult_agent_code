from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class ContextLoader:
    """Loads compact, bounded context for agent prompts."""

    def __init__(
        self,
        root: Path,
        validator: SchemaValidator,
        memory_limit: int = 8,
        acceptance_failure_limit: int = 5,
        workspace_file_limit: int = 20,
        workspace_file_chars: int = 1_200,
        task_failure_limit: int = 5,
        root_guidance_chars: int = 4_000,
    ) -> None:
        self.root = root.resolve()
        self.validator = validator
        self.memory_limit = memory_limit
        self.acceptance_failure_limit = acceptance_failure_limit
        self.workspace_file_limit = workspace_file_limit
        self.workspace_file_chars = workspace_file_chars
        self.task_failure_limit = task_failure_limit
        self.root_guidance_chars = root_guidance_chars
        self.store = JsonStore(validator)
        self.jsonl = JsonlStore(validator)

    def load(self, run_id: str | None = None) -> dict:
        agent_dir = self.root / ".asteria"
        return {
            "memory": self._memory(agent_dir),
            "latest_snapshot": self._latest_snapshot(agent_dir, run_id),
            "latest_handoff": self._latest_handoff(agent_dir),
            "acceptance_failures": self._acceptance_failures(agent_dir),
            "task_failures": self._task_failures(agent_dir, run_id),
            "capability_feedback": CapabilityFeedbackAdvisor(self.validator).planner_hints(
                agent_dir
            ),
            "active_goal": self._active_goal(),
            "root_guidance": self._root_guidance(),
            "workspace_files": self._workspace_files(),
        }

    def _root_guidance(self) -> dict:
        """The project's own guidance file (AGENTS.md at the workspace root — the cross-tool
        single-source convention this project adopts). A ``_root_guidance`` reader already existed in
        ``ContextPackageBuilder`` but was only wired to the WorkerRunner path, so the live execute
        prompt saw AGENTS.md only *incidentally* — as a root ``.md`` truncated to 1200 chars inside
        the 20-file ``workspace_files`` cap (and only if it fit). Surface it deliberately with a
        generous budget so 'read the current directory's guidance' actually happens. (ADR-0024 §5 #3)"""
        path = self.root / "AGENTS.md"
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        return {
            "path": "AGENTS.md",
            "content": content[: self.root_guidance_chars],
            "truncated": len(content) > self.root_guidance_chars,
        }

    def _active_goal(self) -> dict:
        """The durable long-task memory the runtime writes after each run (completed work,
        artifacts already produced, next task, blockers). It is written by ``ActiveGoalMemory``
        but was never fed back to the executing model — so a resumed/continued run started blind,
        re-doing work and re-writing files it had already produced. Surface a bounded, prompt-safe
        projection here so the doer actually sees its own prior progress. Best-effort: absent or
        damaged memory returns ``{}`` (never blocks context loading)."""
        memory = ActiveGoalMemory(self.root)
        try:
            structured = memory.read_structured()
        except Exception:  # noqa: BLE001 - context loading is best effort; damaged memory is not fatal
            return {}
        if not isinstance(structured, dict) or not structured.get("current_goal"):
            return {}
        result = structured.get("current_result")
        return {
            "current_goal": structured.get("current_goal"),
            "current_result": result if isinstance(result, dict) else {},
            "overall_plan": [
                {
                    "title": item.get("title"),
                    "status": item.get("status"),
                }
                for item in structured.get("overall_plan", [])
                if isinstance(item, dict)
            ][:12],
            "completed_work": [str(item) for item in structured.get("completed_work", [])][:8],
            **self._artifact_status(
                [str(item) for item in structured.get("artifact_refs", [])][:10]
            ),
            "next_task": [str(item) for item in structured.get("next_task", [])][:5],
            "current_blockers": [str(item) for item in structured.get("current_blockers", [])][:5],
        }

    def _artifact_status(self, refs: list[str]) -> dict:
        """Split recorded artifact refs by whether they still exist on disk.

        Memory records artifacts by path, but nothing ever reconciled those paths against the
        filesystem, so a file that was reverted, moved, or never landed kept being handed to the
        doer as "already produced" — a stale claim the model has no way to check. Reporting the
        misses under a separate key tells it the truth instead. Best-effort: a path we cannot stat
        counts as present, since only a definite miss justifies contradicting the record.
        """
        present: list[str] = []
        missing: list[str] = []
        for ref in refs:
            try:
                candidate = Path(ref)
                if not candidate.is_absolute():
                    candidate = self.root / candidate
                (present if candidate.exists() else missing).append(ref)
            except OSError:
                present.append(ref)
        return {
            "artifacts_already_produced": present,
            "artifacts_recorded_but_missing": missing,
        }

    def _memory(self, agent_dir: Path) -> list[dict]:
        memory_dir = agent_dir / "memory"
        if not memory_dir.exists():
            return []
        entries: list[dict] = []
        for path in sorted(memory_dir.glob("*.jsonl")):
            entries.extend(self._safe_read_jsonl(path, "memory_entry"))
        entries.sort(key=lambda item: str(item.get("created_at", "")))
        return [
            {
                "type": entry["type"],
                "content": entry["content"],
                "source": entry.get("source", {}),
                "tags": entry.get("tags", []),
                "confidence": entry.get("confidence"),
                "created_at": entry.get("created_at"),
            }
            for entry in entries[-self.memory_limit :]
        ]

    def _latest_snapshot(self, agent_dir: Path, run_id: str | None) -> dict:
        snapshots_dir = agent_dir / "context" / "snapshots"
        candidates: list[Path] = []
        if snapshots_dir.exists():
            candidates = sorted(snapshots_dir.glob("*.json"))
            if run_id:
                run_matches = [
                    path
                    for path in candidates
                    if self._safe_read(path, "context_snapshot").get("run_id") == run_id
                ]
                if run_matches:
                    candidates = run_matches
        if not candidates:
            root_snapshot = agent_dir / "context" / "root_snapshot.json"
            if root_snapshot.exists():
                candidates = [root_snapshot]
        if not candidates:
            return {}
        snapshot = self.store.read(candidates[-1], "context_snapshot")
        result: dict = {
            "snapshot_id": snapshot["snapshot_id"],
            "focus": snapshot["focus"],
            "compaction_purpose": snapshot.get(
                "compaction_purpose", "continuation_state_not_success_evidence"
            ),
            "goal_summary": snapshot["goal_summary"],
            "accepted_decisions": snapshot.get("accepted_decisions", [])[-5:],
            "pending_decisions": snapshot.get("pending_decisions", [])[-5:],
            "active_tasks": snapshot.get("active_tasks", [])[-10:],
            "modified_files": snapshot.get("modified_files", [])[-10:],
            "verification": snapshot.get("verification", [])[-5:],
            "failures": snapshot.get("failures", [])[-5:],
            "failed_tool_observations": snapshot.get("failed_tool_observations", [])[-5:],
            "task_failures": snapshot.get("task_failures", [])[-5:],
            "open_risks": snapshot.get("open_risks", [])[-5:],
            "next_actions": snapshot.get("next_actions", [])[-5:],
        }
        capability_manifest_ref = snapshot.get("capability_manifest_ref")
        if capability_manifest_ref:
            result["capability_manifest_ref"] = capability_manifest_ref
        return result

    def _latest_handoff(self, agent_dir: Path) -> dict:
        handoffs_dir = agent_dir / "context" / "handoffs"
        if not handoffs_dir.exists():
            return {}
        candidates = sorted(handoffs_dir.glob("*.json"))
        if not candidates:
            return {}
        handoff = self.store.read(candidates[-1], "handoff_package")
        return {
            "handoff_id": handoff["handoff_id"],
            "to_role": handoff["to_role"],
            "snapshot_id": handoff["snapshot_id"],
            "current_task_ids": handoff.get("current_task_ids", []),
            "recent_artifacts": handoff.get("recent_artifacts", [])[-10:],
            "known_risks": handoff.get("known_risks", [])[-5:],
            "recommended_next_command": handoff.get("recommended_next_command"),
            "created_at": handoff.get("created_at"),
        }

    def _acceptance_failures(self, agent_dir: Path) -> list[dict]:
        failures_dir = agent_dir / "acceptance" / "failures"
        if not failures_dir.exists():
            return []
        entries = []
        for path in sorted(failures_dir.glob("*.json")):
            evidence = self._safe_read(path, "acceptance_failure_evidence")
            if not evidence:
                continue
            entries.append(
                {
                    "scenario": evidence["scenario"],
                    "suite": evidence["suite"],
                    "failure_summary": evidence["failure_summary"],
                    "evidence_path": path.relative_to(self.root).as_posix(),
                    "promoted_task_id": evidence["promoted_task_id"],
                    "workspace": evidence.get("workspace"),
                    "transcript": evidence.get("transcript"),
                    "expected_file": evidence.get("expected_file"),
                    "reproduce": evidence.get("reproduce", {}),
                    "created_at": evidence.get("created_at"),
                }
            )
        entries.sort(key=lambda item: str(item.get("created_at", "")))
        return entries[-self.acceptance_failure_limit :]

    def _task_failures(self, agent_dir: Path, run_id: str | None) -> list[dict]:
        run_dirs = []
        runs_dir = agent_dir / "runs"
        if run_id:
            run_dirs = [runs_dir / run_id]
        elif runs_dir.exists():
            run_dirs = sorted([path for path in runs_dir.iterdir() if path.is_dir()])[-3:]

        entries = []
        for run_dir in run_dirs:
            path = run_dir / "task_failures.jsonl"
            if not path.exists():
                continue
            for evidence in self.jsonl.read_all(path, "task_failure_evidence"):
                entries.append(
                    {
                        "evidence_id": evidence["evidence_id"],
                        "run_id": evidence.get("run_id"),
                        "task_id": evidence["task_id"],
                        "phase": evidence["phase"],
                        "failure_type": evidence["failure_type"],
                        "summary": evidence["summary"],
                        "contract_check": evidence.get("contract_check", {}),
                        "recommendations": evidence.get("recommendations", [])[:5],
                        "created_at": evidence.get("created_at"),
                    }
                )
        entries.sort(key=lambda item: str(item.get("created_at", "")))
        return entries[-self.task_failure_limit :]

    def workspace_files(self) -> list[dict]:
        """Public, standalone re-scan of the workspace file snapshot. ``load()`` captures
        ``workspace_files`` once at run start; ExecuteCommand refreshes it per task via this method so
        a task sees files that EARLIER tasks in the same run already wrote (the run-end
        ``active_goal`` refresh cannot fill that in-run gap). Without it, multi-task runs had the doer
        re-creating a file a prior task had just produced. (ADR-0024 §5 #1)"""
        return self._workspace_files()

    def _workspace_files(self) -> list[dict]:
        files: list[dict] = []
        for path in sorted(self.root.rglob("*"), key=self._file_sort_key):
            if len(files) >= self.workspace_file_limit:
                break
            if not path.is_file() or self._is_excluded(path):
                continue
            relative = path.relative_to(self.root).as_posix()
            item: dict[str, object] = {"path": relative}
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                item["omitted"] = "non_utf8"
            except OSError:
                item["omitted"] = "unreadable"
            else:
                item["content"] = content[: self.workspace_file_chars]
                item["truncated"] = len(content) > self.workspace_file_chars
            files.append(item)
        return files

    def _file_sort_key(self, path: Path) -> tuple[int, int, str]:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return (999, 999, str(path))
        parts = relative.parts
        suffix_priority = 0 if path.suffix.lower() in {".py", ".md", ".txt"} else 1
        return (suffix_priority, len(parts), relative.as_posix())

    def _is_excluded(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return True
        # AGENTS.md is surfaced deliberately (and with a larger budget) via ``root_guidance``; skip it
        # here so its content is not duplicated in the prompt and it does not consume a workspace slot.
        if relative.as_posix() == "AGENTS.md":
            return True
        parts = set(relative.parts)
        if parts & {".asteria", ".git", "secrets", "__pycache__", ".pytest_cache"}:
            return True
        name = path.name.lower()
        if name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key")):
            return True
        if name in {"id_rsa", "id_ed25519"}:
            return True
        return path.suffix.lower() not in {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}

    def _safe_read(self, path: Path, schema_name: str) -> dict:
        try:
            return self.store.read(path, schema_name)
        except Exception:  # noqa: BLE001 - context loading should be best effort
            return {}

    def _safe_read_jsonl(self, path: Path, schema_name: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    continue
                self.validator.validate(schema_name, item)
            except Exception:  # noqa: BLE001 - context loading should skip stale evidence rows
                continue
            entries.append(item)
        return entries
