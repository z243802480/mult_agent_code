from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


def _validator() -> SchemaValidator:
    return SchemaValidator(Path.cwd() / "schemas")


def _runtime_request(request_id: str, status: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "runtime_request_id": request_id,
        "run_id": "run-0001",
        "task_id": "task-0001",
        "request_type": "scope_expansion",
        "risk": "low",
        "reason": "expand scope",
        "details": {},
        "status": status,
        "created_at": "2026-07-02T00:00:00Z",
    }


def test_rewrite_all_validates_and_replaces_atomically(tmp_path: Path) -> None:
    store = JsonlStore(_validator())
    path = tmp_path / "runtime_requests.jsonl"
    store.append(path, _runtime_request("runtime-request-0001", "recorded"), "runtime_request")

    rows = store.read_all(path, "runtime_request")
    rows[0]["status"] = "auto_applied"
    store.rewrite_all(path, rows, "runtime_request")

    reread = store.read_all(path, "runtime_request")
    assert reread[0]["status"] == "auto_applied"


def test_rewrite_all_rejects_out_of_enum_status(tmp_path: Path) -> None:
    store = JsonlStore(_validator())
    path = tmp_path / "runtime_requests.jsonl"
    with pytest.raises(SchemaValidationError):
        store.rewrite_all(path, [_runtime_request("runtime-request-0001", "bogus")], "runtime_request")
    # Fail closed: nothing persisted on a validation failure.
    assert not path.exists()


def test_packaged_runtime_request_schema_accepts_auto_applied() -> None:
    """Regression: the packaged copy (used by an installed wheel) must accept auto_applied.

    Previously only the repo-root schema enumerated auto_applied, so one auto-apply poisoned
    runtime_requests.jsonl and crashed every later validated read from the wheel.
    """
    packaged = SchemaValidator(Path(str(files("asteria_runtime") / "schemas")))
    packaged.validate("runtime_request", _runtime_request("runtime-request-0001", "auto_applied"))
