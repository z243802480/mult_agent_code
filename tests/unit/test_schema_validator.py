from pathlib import Path

import pytest

from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


def test_schema_validator_accepts_valid_task() -> None:
    validator = SchemaValidator(Path("schemas"))
    validator.validate(
        "task",
        {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Do work",
            "description": "A task",
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": ["passes"],
            "allowed_tools": ["read_file"],
            "expected_artifacts": ["src/example.py"],
        },
    )


def test_schema_validator_rejects_missing_required_key() -> None:
    validator = SchemaValidator(Path("schemas"))
    with pytest.raises(SchemaValidationError):
        validator.validate("task", {"schema_version": "0.1.0"})
