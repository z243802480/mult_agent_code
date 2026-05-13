from pathlib import Path

from agent_runtime.core.context_mount_builder import ContextMountBuilder
from agent_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_context_mount_builder_creates_debug_mount_with_failure_slice() -> None:
    mount = ContextMountBuilder("run-0001").build(
        {
            "task_id": "task-0001",
            "task_kind": "diagnostic",
            "title": "Debug failing test",
        },
        artifact_refs=["artifact-0001"],
        failure_evidence_refs=["failure-0001"],
        decision_refs=["decision-0001"],
    )

    data = mount.to_dict()

    assert data["mount_type"] == "debug_context"
    assert data["includes"]["failure_evidence_refs"] == ["failure-0001"]
    assert data["includes"]["artifact_refs"] == []
    assert data["includes"]["decision_refs"] == []
    SchemaValidator(SCHEMA_DIR).validate("context_mount", data)


def test_context_mount_builder_creates_coding_mount_with_artifact_slice() -> None:
    mount = ContextMountBuilder("run-0001").build(
        {
            "task_id": "task-0002",
            "task_kind": "implementation",
            "title": "Implement feature",
        },
        artifact_refs=["artifact-0001"],
        failure_evidence_refs=["failure-0001"],
    )

    data = mount.to_dict()

    assert data["mount_type"] == "coding_context"
    assert data["includes"]["artifact_refs"] == ["artifact-0001"]
    assert data["includes"]["failure_evidence_refs"] == []
    SchemaValidator(SCHEMA_DIR).validate("context_mount", data)
