from __future__ import annotations

from pathlib import Path

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


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
    ) -> None:
        self.root = root.resolve()
        self.validator = validator
        self.memory_limit = memory_limit
        self.acceptance_failure_limit = acceptance_failure_limit
        self.workspace_file_limit = workspace_file_limit
        self.workspace_file_chars = workspace_file_chars
        self.store = JsonStore(validator)
        self.jsonl = JsonlStore(validator)

    def load(self, run_id: str | None = None) -> dict:
        agent_dir = self.root / ".agent"
        return {
            "memory": self._memory(agent_dir),
            "latest_snapshot": self._latest_snapshot(agent_dir, run_id),
            "latest_handoff": self._latest_handoff(agent_dir),
            "acceptance_failures": self._acceptance_failures(agent_dir),
            "workspace_files": self._workspace_files(),
        }

    def _memory(self, agent_dir: Path) -> list[dict]:
        memory_dir = agent_dir / "memory"
        if not memory_dir.exists():
            return []
        entries: list[dict] = []
        for path in sorted(memory_dir.glob("*.jsonl")):
            entries.extend(self.jsonl.read_all(path, "memory_entry"))
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
        return {
            "snapshot_id": snapshot["snapshot_id"],
            "focus": snapshot["focus"],
            "goal_summary": snapshot["goal_summary"],
            "accepted_decisions": snapshot.get("accepted_decisions", [])[-5:],
            "active_tasks": snapshot.get("active_tasks", [])[-10:],
            "modified_files": snapshot.get("modified_files", [])[-10:],
            "verification": snapshot.get("verification", [])[-5:],
            "failures": snapshot.get("failures", [])[-5:],
            "open_risks": snapshot.get("open_risks", [])[-5:],
            "next_actions": snapshot.get("next_actions", [])[-5:],
        }

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
        parts = set(relative.parts)
        if parts & {".agent", ".git", "secrets", "__pycache__", ".pytest_cache"}:
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
