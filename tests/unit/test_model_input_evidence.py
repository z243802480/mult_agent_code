"""Persist only evidence that occupies the runtime's actual feedback message slots."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from asteria_runtime.core import model_driven_turn as loop
from asteria_runtime.models.base import ChatMessage, ChatResponse, TokenUsage
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator, SchemaValidationError
from tests.unit.test_model_driven_turn import FakeModelClient, FakeToolRunner, FakeToolResult, _json_resp, _resp, _run


def sample(transport="json", *, data=None):
    data = data if data is not None else {"tool_call_id": "call-source", "stdout": "PRIVATE_TOOL_BODY"}
    if transport == "json":
        responses = [_json_resp("check", [{"tool_name": "run_command", "args": {"command": "unchanged"}}]),
                     _json_resp("done", done=True)]
    else:
        responses = [_resp("check", ("run_command", {"command": "unchanged"})), _resp("done")]
    model = FakeModelClient(responses)
    tools = FakeToolRunner([[FakeToolResult(data=data)]])
    result = _run(model, tools, transport=transport)
    assert result.status == "completed"
    return model.requests


@pytest.mark.parametrize("transport", ["json", "tool_use"])
def test_actual_feedback_ids_and_hashes_reach_each_request_without_raw_content(transport):
    first, second = sample(transport)
    assert first.metadata["input_evidence"]["observations"] == []
    trace = second.metadata["input_evidence"]
    assert trace["scope"] == "request_assembly_only"
    assert trace["matched_feedback_messages"] == 1 and trace["unmatched_feedback_messages"] == 0
    observed = trace["observations"][0]
    assert observed["tool_call_id"] == "call-source" and observed["tool_name"] == "run_command"
    assert observed["payload_included"] is True
    assert all(len(observed[k]) == 64 for k in ("payload_sha256", "receipt_sha256", "feedback_sha256"))
    assert "PRIVATE_TOOL_BODY" not in json.dumps(trace)
    assert "PRIVATE_TOOL_BODY" in second.messages[-1].text()
    assert second.metadata["input_evidence"]["messages_sha256"] != first.metadata["input_evidence"]["messages_sha256"]


@pytest.mark.parametrize("case", ["withheld", "wrong_role", "multimodal", "duplicate_slot"])
def test_copied_feedback_elsewhere_does_not_certify_a_changed_or_ambiguous_slot(monkeypatch, case):
    compact = loop._compact_history
    def changed(messages, index, *args, **kwargs):
        compact(messages, index, *args, **kwargs)
        slot = index[-1][0]
        original = messages[slot]
        if case == "duplicate_slot":
            index.append(index[-1])
        else:
            messages[slot] = (ChatMessage("assistant", original.text()) if case == "wrong_role" else
                              ChatMessage("user", [{"type": "text", "text": original.text()}]) if case == "multimodal" else
                              ChatMessage("user", "feedback withheld"))
            messages.append(original)  # Same text at a different, unregistered slot is no proof.
    monkeypatch.setattr(loop, "_compact_history", changed)
    trace = sample()[1].metadata["input_evidence"]
    assert trace["observations"] == [] and trace["unmatched_feedback_messages"] >= 1


@pytest.mark.parametrize("identity", [None, "", "x" * 161])
def test_unknown_or_oversized_ids_are_not_truncated_into_a_source_binding(identity):
    trace = sample(data={"stdout": "observed", "tool_call_id": identity})[1].metadata["input_evidence"]
    assert trace["observations"] == [] and trace["unidentified_observations"] == 1


def test_duplicate_ids_from_different_batches_do_not_choose_an_owner():
    model = FakeModelClient([_json_resp("one", [{"tool_name": "run_command", "args": {}}]),
                             _json_resp("two", [{"tool_name": "run_command", "args": {}}]),
                             _json_resp("done", done=True)])
    tools = FakeToolRunner([[FakeToolResult(data={"tool_call_id": "duplicate", "stdout": "one"})],
                           [FakeToolResult(data={"tool_call_id": "duplicate", "stdout": "two"})]])
    _run(model, tools, transport="json")
    trace = model.requests[-1].metadata["input_evidence"]
    assert trace["observations"] == [] and trace["unidentified_observations"] == 2


def test_history_compression_records_which_payload_is_still_present():
    model = FakeModelClient([_json_resp("one", [{"tool_name": "run_command", "args": {}}]),
                             _json_resp("two", [{"tool_name": "run_command", "args": {}}]),
                             _json_resp("done", done=True)])
    tools = FakeToolRunner([[FakeToolResult(data={"tool_call_id": "one", "stdout": "A" * 5000})],
                           [FakeToolResult(data={"tool_call_id": "two", "stdout": "B" * 5000})]])
    _run(model, tools, transport="json", history_char_budget=8000, keep_recent_observation_payloads=1)
    trace = model.requests[-1].metadata["input_evidence"]
    assert [(r["tool_call_id"], r["payload_included"]) for r in trace["observations"]] == [("one", False), ("two", True)]


def test_capacity_is_explicit_and_does_not_change_the_actual_tool_feedback():
    calls = [{"tool_name": "run_command", "args": {}} for _ in range(80)]
    model = FakeModelClient([_json_resp("batch", calls), _json_resp("done", done=True)])
    tools = FakeToolRunner([[FakeToolResult(data={"tool_call_id": f"source-{i}", "stdout": f"BODY-{i}"}) for i in range(80)]])
    _run(model, tools, transport="json")
    request = model.requests[-1]
    trace = request.metadata["input_evidence"]
    assert len(trace["observations"]) == 64 and trace["omitted_observations"] == 16
    assert trace["observations"][0]["tool_call_id"] == "source-16" and trace["observation_count"] == 80
    assert "BODY-0" in request.messages[-1].text() and len(json.dumps(trace)) < 64_000


def response():
    return ChatResponse("done", None, TokenUsage(11, 3, 14), "fake", "fake", {})


@pytest.mark.parametrize("failed", [False, True])
def test_success_and_failure_logs_persist_assembly_evidence_without_content(tmp_path, failed):
    request = sample()[1]
    logger = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas")))
    record = (logger.record_failure(request, "fake", "fake", "medium", "provider unavailable") if failed else
              logger.record_success(request, response()))
    assert record["input_evidence"]["status"] == "matched"
    assert record["input_evidence"]["observations"][0]["tool_call_id"] == "call-source"
    text = (tmp_path / "model_calls.jsonl").read_text(encoding="utf8")
    assert "PRIVATE_TOOL_BODY" not in text and "unchanged" not in text
    assert record["status"] == ("failure" if failed else "success")


def test_logger_drops_links_if_messages_changed_after_loop_assembly(tmp_path):
    request = sample()[1]
    modified = replace(request, messages=[ChatMessage("user", "new request content")])
    record = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))).record_success(modified, response())
    trace = record["input_evidence"]
    assert trace["status"] == "messages_changed" and trace["observations"] == []
    assert trace["messages_sha256"] != trace["assembly_messages_sha256"]


@pytest.mark.parametrize("case", ["extra", "dispatch", "digest", "negative", "over_capacity", "payload_type"])
def test_invalid_metadata_is_not_persisted_or_allowed_to_break_a_successful_call(tmp_path, case):
    request = sample()[1]
    trace = request.metadata["input_evidence"]
    if case == "extra":
        trace["raw_content"] = "PRIVATE_EXTRA_BODY"
    elif case == "dispatch":
        trace["observations"][0]["dispatch_state"] = {}
    elif case == "digest":
        trace["observations"][0]["receipt_sha256"] = "not-a-digest"
    elif case == "negative":
        trace["observation_count"] = -1
    elif case == "over_capacity":
        trace["observations"] *= 65
    else:
        trace["observations"][0]["payload_included"] = "yes"
    record = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))).record_success(request, response())
    assert record["input_evidence"]["status"] == "invalid" and record["input_evidence"]["observations"] == []
    assert "PRIVATE_EXTRA_BODY" not in (tmp_path / "model_calls.jsonl").read_text()


def test_call_attribution_cannot_supply_a_forged_input_receipt():
    model = FakeModelClient([_json_resp("done", done=True)])
    _run(model, FakeToolRunner([]), transport="json", call_attribution={"input_evidence": {"forged": True}})
    trace = model.requests[0].metadata["input_evidence"]
    assert "forged" not in trace and trace["observations"] == []


def test_old_requests_remain_schema_valid_without_backfilling_input_evidence(tmp_path):
    request = replace(sample()[1], metadata={})
    record = ModelCallLogger(tmp_path, SchemaValidator(Path("schemas"))).record_success(request, response())
    assert "input_evidence" not in record


def test_schema_checks_the_new_persisted_boundary(tmp_path):
    validator = SchemaValidator(Path("schemas"))
    record = ModelCallLogger(tmp_path, validator).record_success(sample()[1], response())
    bad = deepcopy(record)
    bad["input_evidence"]["observations"][0]["payload_included"] = "yes"
    with pytest.raises(SchemaValidationError):
        validator.validate("model_call", bad)


def test_runtime_metadata_does_not_change_the_provider_payload():
    from asteria_runtime.models.openai_compatible import OpenAICompatibleClient
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.settings = SimpleNamespace(model_name="fake", streaming_enabled=False)
    client.provider = "fake"
    request = sample()[1]
    assert "input_evidence" in request.metadata
    assert client._payload(request) == client._payload(replace(request, metadata={}))
