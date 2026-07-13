from __future__ import annotations

import json
from threading import RLock
from pathlib import Path
from typing import Any

from asteria_runtime.storage.audit_chain import (
    append_chain_entry,
    audit_chain_enabled,
    is_audit_file,
    rechain_file,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


_JSONL_APPEND_LOCK = RLock()


class JsonlStore:
    def __init__(self, validator: SchemaValidator | None = None) -> None:
        self.validator = validator

    def append(self, path: Path, data: dict[str, Any], schema_name: str | None = None) -> None:
        if schema_name and self.validator:
            self.validator.validate(schema_name, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        record_line = json.dumps(data, ensure_ascii=False)
        with _JSONL_APPEND_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record_line + "\n")
            # Tamper-evidence (S77 P1, opt-in): bind this record into the append-only hash chain at
            # the single write chokepoint — the exact bytes just written. Off by default = no-op.
            if audit_chain_enabled() and is_audit_file(path):
                append_chain_entry(path, record_line)

    def rewrite_all(
        self, path: Path, rows: list[dict[str, Any]], schema_name: str | None = None
    ) -> None:
        """Atomically replace a JSONL file, validating every row first (fail closed).

        Callers that rewrite an existing row (status transitions, redaction) must not fall back
        to a raw write_text that bypasses validation — that let ``status='auto_applied'`` (an
        enum value only the repo-root schema knew) poison runtime_requests.jsonl and crash every
        later validated read on an installed wheel.
        """
        if schema_name and self.validator:
            for row in rows:
                self.validator.validate(schema_name, row)
        path.parent.mkdir(parents=True, exist_ok=True)
        record_lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        payload = "".join(line + "\n" for line in record_lines)
        with _JSONL_APPEND_LOCK:
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)
            # A legitimate atomic rewrite (status transition / redaction) re-seals the chain over the
            # new rows; a raw edit that skips rewrite_all is caught by verify (chain diverges).
            if audit_chain_enabled() and is_audit_file(path):
                rechain_file(path, record_lines)

    def read_all(self, path: Path, schema_name: str | None = None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc
                if schema_name and self.validator:
                    self.validator.validate(schema_name, data)
                rows.append(data)
        return rows
