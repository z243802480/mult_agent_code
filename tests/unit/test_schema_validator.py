from pathlib import Path

import pytest

from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator

pytestmark = pytest.mark.contract


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


def test_control_surface_contract_schema_accepts_additive_contract() -> None:
    validator = SchemaValidator(Path("schemas"))

    validator.validate(
        "control_surface",
        {
            "schema_version": "0.1.0",
            "command": "status",
            "audience": "user_workflow",
            "stability": "additive",
            "stable_fields": ["schema_version", "status", "next_actions"],
        },
    )


def test_control_surface_contract_schema_rejects_unknown_stability() -> None:
    validator = SchemaValidator(Path("schemas"))

    with pytest.raises(SchemaValidationError):
        validator.validate(
            "control_surface",
            {
                "schema_version": "0.1.0",
                "command": "status",
                "audience": "user_workflow",
                "stability": "breaking",
                "stable_fields": ["schema_version"],
            },
        )
