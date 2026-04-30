from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.commands.verification_command import VerificationStatusCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_verification_status_reports_missing_summary(tmp_path: Path) -> None:
    result = VerificationStatusCommand(tmp_path).run()

    assert result.summary is None
    assert "Verification summary: none" in result.to_text()


def test_verification_status_reads_schema_validated_summary(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    summary = {
        "schema_version": "0.1.0",
        "created_at": "2026-04-30T10:00:00+08:00",
        "status": "passed",
        "platform": "windows",
        "checks": [
            {"name": "pytest", "status": "passed", "summary": "full test suite passed"},
            {"name": "handoff", "status": "passed", "summary": "handoff package created"},
        ],
        "artifacts": {"snapshot_count": 1, "handoff_count": 1},
    }
    JsonStore(validator).write(
        tmp_path / ".agent" / "verification" / "latest.json",
        summary,
        "verification_summary",
    )

    result = VerificationStatusCommand(tmp_path).run()
    text = result.to_text()

    assert result.summary == summary
    assert "Status: passed" in text
    assert "pytest: passed" in text
    assert "handoff_count: 1" in text
    validator.validate("verification_summary", json.loads(result.summary_path.read_text()))
