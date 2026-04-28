from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.security.path_guard import PathGuard
from agent_runtime.storage.json_store import JsonStore

SCHEMA_VERSION = "0.1.0"


class FileBackupStore:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.store = JsonStore(context.validator)

    def backup_paths(self, paths: list[Path], reason: str) -> dict:
        backup_id = self._backup_id()
        backup_dir = self._backup_dir(backup_id)
        files_dir = backup_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        records = []
        seen: set[str] = set()
        for path in paths:
            rel = path.relative_to(self.context.root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            if path.exists() and path.is_file():
                backup_name = self._backup_file_name(rel)
                backup_path = files_dir / backup_name
                shutil.copy2(path, backup_path)
                records.append(
                    {
                        "path": rel,
                        "existed": True,
                        "backup_path": backup_path.relative_to(backup_dir).as_posix(),
                        "size": path.stat().st_size,
                    }
                )
            else:
                records.append(
                    {
                        "path": rel,
                        "existed": False,
                        "backup_path": None,
                        "size": None,
                    }
                )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": backup_id,
            "run_id": self.context.run_id,
            "created_at": self._now(),
            "reason": reason,
            "files": records,
        }
        self.store.write(backup_dir / "manifest.json", manifest, "file_backup_manifest")
        if self.context.event_logger:
            self.context.event_logger.record(
                self.context.run_id,
                "file_backup_created",
                "FileBackupStore",
                f"Created backup {backup_id} for {len(records)} file(s)",
                {"backup_id": backup_id, "reason": reason, "files": [item["path"] for item in records]},
            )
        return manifest

    def restore(self, backup_id: str, delete_created_files: bool = False) -> dict:
        manifest_path = self._find_manifest(backup_id)
        manifest = self.store.read(manifest_path, "file_backup_manifest")
        backup_dir = manifest_path.parent
        guard = PathGuard(self.context.root, self.context.policy["protected_paths"])
        restored: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []

        for item in manifest["files"]:
            target = guard.resolve_for_write(item["path"])
            if item["existed"]:
                source_rel = item["backup_path"]
                if not source_rel:
                    skipped.append(item["path"])
                    warnings.append(f"Missing backup file for {item['path']}")
                    continue
                source = backup_dir / source_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                restored.append(item["path"])
            elif target.exists():
                if delete_created_files:
                    target.unlink()
                    restored.append(item["path"])
                else:
                    skipped.append(item["path"])
                    warnings.append(
                        f"Created file left in place because delete_created_files is false: {item['path']}"
                    )

        if self.context.event_logger:
            self.context.event_logger.record(
                self.context.run_id,
                "file_backup_restored",
                "FileBackupStore",
                f"Restored backup {backup_id}",
                {"backup_id": backup_id, "restored": restored, "skipped": skipped, "warnings": warnings},
            )
        return {"backup_id": backup_id, "restored": restored, "skipped": skipped, "warnings": warnings}

    def _backup_dir(self, backup_id: str) -> Path:
        run_segment = self.context.run_id or "no-run"
        return self.context.agent_dir / "backups" / run_segment / backup_id

    def _find_manifest(self, backup_id: str) -> Path:
        if any(part in backup_id for part in ["/", "\\", ".."]):
            raise ValueError(f"Invalid backup_id: {backup_id}")
        backups_root = self.context.agent_dir / "backups"
        matches = list(backups_root.glob(f"*/{backup_id}/manifest.json")) if backups_root.exists() else []
        if not matches:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        if len(matches) > 1:
            raise ValueError(f"Backup id is ambiguous: {backup_id}")
        return matches[0]

    def _backup_id(self) -> str:
        return "backup-" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")

    def _backup_file_name(self, rel_path: str) -> str:
        digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]
        return f"{digest}.bak"

    def _now(self) -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
