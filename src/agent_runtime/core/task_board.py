from __future__ import annotations

from pathlib import Path

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class TaskStateError(ValueError):
    pass


ALLOWED_TRANSITIONS = {
    "backlog": {"ready", "discarded"},
    "ready": {"in_progress", "blocked", "discarded"},
    "in_progress": {"testing", "blocked", "discarded"},
    "testing": {"reviewing", "blocked", "in_progress", "discarded"},
    "reviewing": {"done", "blocked", "in_progress", "discarded"},
    "blocked": {"ready", "discarded"},
    "done": set(),
    "discarded": set(),
}


class TaskBoard:
    def __init__(self, path: Path, validator: SchemaValidator | None = None) -> None:
        self.path = path
        self.validator = validator
        self.store = JsonStore(validator)
        if not self.path.exists():
            self.store.write(self.path, {"schema_version": "0.1.0", "tasks": []}, "task_board")

    def list_tasks(self) -> list[dict]:
        return self._load()["tasks"]

    def add_task(self, task: dict) -> None:
        if self.validator:
            self.validator.validate("task", task)
        data = self._load()
        if any(existing["task_id"] == task["task_id"] for existing in data["tasks"]):
            raise TaskStateError(f"Task already exists: {task['task_id']}")
        data["tasks"].append(task)
        self._save(data)

    def get_task(self, task_id: str) -> dict:
        for task in self.list_tasks():
            if task["task_id"] == task_id:
                return task
        raise TaskStateError(f"Task not found: {task_id}")

    def update_status(self, task_id: str, new_status: str) -> dict:
        data = self._load()
        for task in data["tasks"]:
            if task["task_id"] == task_id:
                old_status = task["status"]
                if new_status not in ALLOWED_TRANSITIONS[old_status]:
                    raise TaskStateError(f"Invalid task transition: {old_status} -> {new_status}")
                task["status"] = new_status
                task["updated_at"] = now_iso()
                self._save(data)
                return task
        raise TaskStateError(f"Task not found: {task_id}")

    def update_notes(self, task_id: str, notes: str) -> dict:
        data = self._load()
        for task in data["tasks"]:
            if task["task_id"] == task_id:
                task["notes"] = notes
                task["updated_at"] = now_iso()
                self._save(data)
                return task
        raise TaskStateError(f"Task not found: {task_id}")

    def promote_unblocked(self) -> list[dict]:
        data = self._load()
        done = {task["task_id"] for task in data["tasks"] if task["status"] == "done"}
        promoted = []
        for task in data["tasks"]:
            if task["status"] == "backlog" and all(dep in done for dep in task["depends_on"]):
                task["status"] = "ready"
                task["updated_at"] = now_iso()
                promoted.append(task)
        if promoted:
            self._save(data)
        return promoted

    def ready_tasks(self) -> list[dict]:
        tasks = self.list_tasks()
        done = {task["task_id"] for task in tasks if task["status"] == "done"}
        ready = []
        for task in tasks:
            if task["status"] == "ready" and all(dep in done for dep in task["depends_on"]):
                ready.append(task)
        return ready

    def _load(self) -> dict:
        return self.store.read(self.path, "task_board")

    def _save(self, data: dict) -> None:
        self.store.write(self.path, data, "task_board")
