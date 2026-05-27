from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.chat_context_builder import ChatContextBuilder
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_chat_context_builder_wraps_payload_in_auditable_envelope(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    builder = ChatContextBuilder(tmp_path, SchemaValidator(SCHEMA_DIR))
    envelope = builder.build(intent="ordinary_chat").to_dict()

    SchemaValidator(SCHEMA_DIR).validate("context_envelope", envelope)
    assert envelope["audience"] == "user_interaction"
    assert envelope["mode"] == "chat"
    assert envelope["intent"] == "ordinary_chat"
    assert envelope["run_id"] is None
    assert envelope["payload"]["chat_intent"] == "ordinary_chat"
    assert envelope["payload"]["capability_invocation_policy"]["intent"] == "ordinary_chat"
    assert envelope["payload"]["capability_invocation_policy"]["allow_tools"] is False
    assert envelope["payload"]["active_goal_memory"] == ""
    assert envelope["payload_hash"]
    assert envelope["refs"] == [".asteria/project.json", ".asteria/policies.json"]
    assert envelope["redaction_policy"]["backend_fields_allowed"] is False
    assert {
        item["name"]: item["included"] for item in envelope["sections"]
    }["active_goal_memory"] is False
    assert {
        item["name"]: item["included"] for item in envelope["sections"]
    }["capability_invocation_policy"] is True


def test_chat_context_builder_persists_envelope(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    builder = ChatContextBuilder(tmp_path, SchemaValidator(SCHEMA_DIR))

    context, envelope, path = builder.build_and_persist(intent="ordinary_chat")

    assert context == envelope.payload
    assert path == tmp_path / ".asteria" / "context" / "context_envelope_chat.json"
    assert path.exists()
    persisted = JsonStore(SchemaValidator(SCHEMA_DIR)).read(path, "context_envelope")
    assert persisted["payload_hash"] == envelope.payload_hash
