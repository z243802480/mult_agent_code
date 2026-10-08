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


def test_validator_enforces_declared_minimum_instead_of_ignoring_it() -> None:
    # Reaudit debt #5①: run_loop_summary.schema.json declares iteration_count minimum 0, but the
    # validator silently ignored bounds — a negative count validated green while the schema
    # claimed a gate. The declared bound must actually gate.
    validator = SchemaValidator(Path("schemas"))
    schema = validator._load("run_loop_summary")
    node = schema["properties"]["iteration_count"]
    validator._validate_node(node, 3, "$.iteration_count")
    with pytest.raises(SchemaValidationError, match="expected >= 0"):
        validator._validate_node(node, -1, "$.iteration_count")


def test_validator_enforces_maximum_when_declared() -> None:
    validator = SchemaValidator(Path("schemas"))
    node = {"type": "integer", "minimum": 0, "maximum": 100}
    validator._validate_node(node, 100, "$.x")
    with pytest.raises(SchemaValidationError, match="expected <= 100"):
        validator._validate_node(node, 101, "$.x")


def test_minimum_does_not_reject_booleans_or_strings() -> None:
    # bool is an int in Python; bounds apply to numbers only.
    validator = SchemaValidator(Path("schemas"))
    node = {"type": ["boolean", "integer"], "minimum": 0}
    validator._validate_node(node, True, "$.flag")
