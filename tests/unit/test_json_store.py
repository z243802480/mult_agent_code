from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_write_without_validator_skips_validation(tmp_path: Path) -> None:
    # A store with no validator is raw scratch storage; no schema is required.
    store = JsonStore()
    path = tmp_path / "scratch.json"
    store.write(path, {"any": "data"})
    assert path.exists()


def test_validator_backed_write_fails_closed_without_schema(tmp_path: Path) -> None:
    store = JsonStore(SchemaValidator(Path("schemas")))
    with pytest.raises(ValueError, match="without schema validation"):
        store.write(tmp_path / "obj.json", {"any": "data"})


def test_validator_backed_write_allows_explicit_opt_out(tmp_path: Path) -> None:
    store = JsonStore(SchemaValidator(Path("schemas")))
    path = tmp_path / "obj.json"
    store.write(path, {"any": "data"}, allow_unvalidated=True)
    assert path.exists()


def test_validator_backed_write_validates_when_schema_given(tmp_path: Path) -> None:
    store = JsonStore(SchemaValidator(Path("schemas")))
    path = tmp_path / "current_session.json"
    store.write(
        path,
        {
            "schema_version": "0.1.0",
            "session_id": "run-1",
            "set_at": "2026-06-28T00:00:00+00:00",
            "reason": "test",
        },
        "current_session",
    )
    assert store.read(path, "current_session")["session_id"] == "run-1"


def test_validator_backed_write_rejects_invalid_payload(tmp_path: Path) -> None:
    store = JsonStore(SchemaValidator(Path("schemas")))
    with pytest.raises(Exception):
        # Missing required fields for the current_session schema.
        store.write(tmp_path / "current_session.json", {"unexpected": True}, "current_session")
