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


def test_chat_runtime_summary_reports_project_paths_and_guidance(tmp_path: Path) -> None:
    # runtime_summary read important_paths/guidance off ContextLoader's payload, which has never
    # returned either key — they live in project.json — so the chat model was told the project has
    # no important paths and no guidance on every single turn. Nothing tested this, which is how it
    # stayed dead.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Rules\nStay in scope.\n", encoding="utf-8")
    InitCommand(tmp_path).run()

    payload = ChatContextBuilder(tmp_path, SchemaValidator(SCHEMA_DIR)).context(
        intent="ordinary_chat"
    )

    summary = payload["runtime_summary"]
    project = JsonStore(SchemaValidator(SCHEMA_DIR)).read(
        tmp_path / ".asteria" / "project.json", "project_config"
    )
    assert summary["important_paths"], "detected project paths must reach the chat model"
    assert summary["important_paths"] == project["important_paths"][:10]
    assert summary["guidance"] is True


def test_chat_runtime_summary_guidance_is_false_when_the_file_is_gone(tmp_path: Path) -> None:
    # project.json declares root_guidance_path at init; a declaration is not proof the file is
    # still there, so the flag must be reconciled against disk rather than repeated.
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    InitCommand(tmp_path).run()
    (tmp_path / "AGENTS.md").unlink()

    payload = ChatContextBuilder(tmp_path, SchemaValidator(SCHEMA_DIR)).context(
        intent="ordinary_chat"
    )

    assert payload["runtime_summary"]["guidance"] is False
