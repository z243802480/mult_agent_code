import json
import subprocess
import sys
from pathlib import Path

import pytest

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.model_input_evidence import messages_sha256
from asteria_runtime.models.base import ChatMessage, ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def setup(root):
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    policy = {"budgets": {"max_model_calls_per_goal": 100}}
    run = root / ".asteria/runs/run-prepared"
    budget = BudgetController.from_run(policy, run, validator)
    return validator, policy, run, budget, ModelCallLogger(run, validator)


def request():
    return ChatRequest(purpose="model_check", model_tier="strong",
                       messages=[ChatMessage(role="user", content="private prompt marker")],
                       metadata={"run_id": "run-prepared", "task_id": "task-1"})


def response():
    return ChatResponse(content="private response marker", finish_reason="stop", usage=TokenUsage(10, 5, 15),
                        model_provider="echoed-provider", model_name="echoed-model", raw_response={})


@pytest.mark.parametrize("fail", [False, True])
def test_prepared_is_durable_before_delegate_and_links_terminal_without_raw_content(tmp_path, fail):
    validator, policy, run, budget, logger = setup(tmp_path)
    req = request()

    class Delegate:
        def chat(self, actual):
            prepared = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
            assert len(prepared) == 1
            row = prepared[0]
            assert row["status"] == "prepared" and row["dispatch_state"] == "unobserved"
            assert row["scope"] == "logical_provider_call"
            assert row["messages_sha256"] == messages_sha256(actual.messages)
            assert not (run / "model_calls.jsonl").exists()
            if fail:
                raise RuntimeError("connection lost")
            return response()

    client = MeteredModelClient(Delegate(), budget, logger)
    if fail:
        with pytest.raises(RuntimeError, match="connection lost"):
            client.chat(req)
    else:
        client.chat(req)
    prepared = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
    terminal = JsonlStore(validator).read_all(run / "model_calls.jsonl", "model_call")
    assert terminal[0]["request_attempt_id"] == prepared[0]["request_attempt_id"]
    raw = (run / "model_request_attempts.jsonl").read_text()
    assert "private prompt marker" not in raw and "private response marker" not in raw
    before = {p.name: p.read_bytes() for p in run.glob("*.jsonl")}
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == report["strong_model_calls"] == 1
    assert report["estimated_input_tokens"] == (None if fail else 10)
    assert BudgetController.from_run(policy, run, validator).cost_report() == report
    assert all((run / name).read_bytes() == data for name, data in before.items())


def test_journal_failure_blocks_delegate_but_does_not_refund_admitted_budget(tmp_path, monkeypatch):
    validator, policy, run, budget, logger = setup(tmp_path)
    called = []

    class Delegate:
        def chat(self, req):
            called.append(req)
            return response()

    def fail(*args, **kwargs):
        raise OSError("journal unavailable")

    monkeypatch.setattr(logger.store, "append", fail)
    with pytest.raises(OSError, match="journal unavailable"):
        MeteredModelClient(Delegate(), budget, logger).chat(request())
    assert called == []
    assert BudgetController.from_run(policy, run, validator).cost_report()["model_calls"] == 1


def test_offline_client_also_links_prepared_without_changing_response(tmp_path):
    validator, _, run, budget, logger = setup(tmp_path)
    result = FakeModelClient(logger, budget).chat(request())
    assert json.loads(result.content) == {"ok": True}
    starts = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
    ends = JsonlStore(validator).read_all(run / "model_calls.jsonl", "model_call")
    assert len(starts) == len(ends) == 1
    assert ends[0]["request_attempt_id"] == starts[0]["request_attempt_id"]


@pytest.mark.parametrize("lose_checkpoint", [False, True])
def test_real_process_exit_leaves_prepared_and_unknown_usage_without_inventing_dispatch(tmp_path, lose_checkpoint):
    validator, policy, run, _, _ = setup(tmp_path)
    source = Path(__file__).resolve().parents[2] / "src"
    code = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.models.base import ChatMessage, ChatRequest
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.schema_validator import SchemaValidator
run = Path(sys.argv[2]); validator = SchemaValidator(Path(sys.argv[3]))
budget = BudgetController.from_run(json.loads(sys.argv[4]), run, validator)
class Exit:
    def chat(self, request):
        os._exit(23)
request = ChatRequest(purpose='task_execution', model_tier='strong',
    messages=[ChatMessage(role='user', content='private')],
    metadata={'run_id': run.name, 'task_id': 'task-1'})
MeteredModelClient(Exit(), budget, ModelCallLogger(run, validator)).chat(request)
"""
    result = subprocess.run([sys.executable, "-c", code, str(source), str(run), str(source.parent / "schemas"),
                             json.dumps(policy)], capture_output=True, timeout=30)
    assert result.returncode == 23, result.stderr
    assert not (run / "model_calls.jsonl").exists()
    if lose_checkpoint:
        (run / "cost_report.json").unlink()
    raw = (run / "model_request_attempts.jsonl").read_bytes()
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == report["strong_model_calls"] == 1
    assert report["estimated_input_tokens"] is report["estimated_output_tokens"] is None
    meta = report["accounting_recovery"]
    assert meta["unresolved_model_requests"] == meta["unrecorded_model_attempts"] == 1
    assert meta["known_input_tokens_lower_bound"] == meta["known_output_tokens_lower_bound"] == 0
    assert BudgetController.from_run(policy, run, validator).cost_report() == report
    assert (run / "model_request_attempts.jsonl").read_bytes() == raw


def test_pending_and_completed_and_legacy_do_not_double_charge_and_keep_known_lower_bound(tmp_path):
    validator, policy, run, budget, logger = setup(tmp_path)
    MeteredModelClient(type("Delegate", (), {"chat": lambda self, req: response()})(), budget, logger).chat(request())
    logger.record_success(request(), response())  # historical terminal without a prepared ID
    logger.record_prepared(request(), "metered", "external")
    stale = JsonStore(validator).read(run / "cost_report.json", "cost_report")
    stale["model_calls"] = stale["strong_model_calls"] = 0
    JsonStore(validator).write(run / "cost_report.json", stale, "cost_report")
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == report["strong_model_calls"] == 3
    assert report["estimated_input_tokens"] is None
    assert report["accounting_recovery"]["known_input_tokens_lower_bound"] == 20
    assert report["accounting_recovery"]["known_output_tokens_lower_bound"] == 10
    assert report["accounting_recovery"]["unresolved_model_requests"] == 1
    assert BudgetController.from_run(policy, run, validator).cost_report() == report


@pytest.mark.parametrize("conflict", ["duplicate_start", "duplicate_end", "run_id", "task_id", "purpose", "model_tier"])
def test_ambiguous_linkage_fails_closed_before_overwriting_budget(tmp_path, conflict):
    validator, policy, run, _, logger = setup(tmp_path)
    req = request()
    attempt_id = logger.record_prepared(req, "metered", "external")
    terminal = logger.record_success(req, response(), request_attempt_id=attempt_id)
    store = JsonlStore(validator)
    if conflict == "duplicate_start":
        row = store.read_all(run / "model_request_attempts.jsonl", "model_request_attempt")[0]
        store.append(run / "model_request_attempts.jsonl", row, "model_request_attempt")
    elif conflict == "duplicate_end":
        store.append(run / "model_calls.jsonl", terminal, "model_call")
    else:
        row = store.read_all(run / "model_request_attempts.jsonl", "model_request_attempt")[0]
        row[conflict] = "different"
        store.rewrite_all(run / "model_request_attempts.jsonl", [row], "model_request_attempt")
    before = (run / "cost_report.json").read_bytes()
    with pytest.raises(ValueError, match="model request"):
        BudgetController.from_run(policy, run, validator)
    assert (run / "cost_report.json").read_bytes() == before


def test_unknown_terminal_identity_does_not_erase_a_prepared_request(tmp_path):
    validator, policy, run, _, logger = setup(tmp_path)
    logger.record_prepared(request(), "metered", "external")
    logger.record_success(request(), response(), request_attempt_id="unrelated")
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == 2
    assert report["accounting_recovery"]["unresolved_model_requests"] == 1
    assert report["accounting_recovery"]["orphan_model_terminals"] == 1


def test_logger_without_run_dir_keeps_legacy_behavior():
    logger = ModelCallLogger(None)
    assert logger.record_prepared(request(), "any", "any") is None
    assert "request_attempt_id" not in logger.record_success(request(), response())


@pytest.mark.parametrize("transport", ["json", "tool_use"])
def test_prepared_saves_current_assembly_receipt_without_claiming_history_absence(tmp_path, transport):
    from tests.unit.test_model_input_evidence import sample
    validator, _, run, _, logger = setup(tmp_path)
    initial, next_turn = sample(transport)
    for req in (initial, next_turn):
        logger.record_prepared(req, "configured-provider", "configured-model")
    starts = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
    assert starts[0]["input_evidence"]["observations"] == []
    assert starts[1]["input_evidence"]["observations"][0]["tool_call_id"] == "call-source"
    assert starts[1]["messages_sha256"] == starts[1]["input_evidence"]["messages_sha256"]
    assert starts[1]["input_evidence"]["scope"] == "request_assembly_only"
    assert "PRIVATE_TOOL_BODY" not in (run / "model_request_attempts.jsonl").read_text()


@pytest.mark.parametrize("backend", ["openai_compatible", "minimax"])
def test_http_retry_is_one_logical_preparation_and_does_not_send_the_identity(tmp_path, monkeypatch, backend):
    from asteria_runtime.models.http_transport import HttpResponse, HttpTransportError
    from asteria_runtime.models.openai_compatible import OpenAICompatibleClient, OpenAICompatibleSettings
    from asteria_runtime.models.minimax import MiniMaxOpenAICompatibleClient, MiniMaxSettings
    validator, policy, run, budget, logger = setup(tmp_path)
    calls = []

    class Transport:
        def post_json(self, url, headers, payload, timeout_seconds):
            starts = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
            assert len(starts) == 1
            assert "request_attempt_id" not in payload and "input_evidence" not in payload
            calls.append(payload)
            if len(calls) == 1:
                raise HttpTransportError("timeout")
            return HttpResponse(200, {"model": "server-echo", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    monkeypatch.setattr("asteria_runtime.models." + backend + ".time.sleep", lambda _: None)
    client_class, settings_class = ((OpenAICompatibleClient, OpenAICompatibleSettings) if backend == "openai_compatible" else
                                    (MiniMaxOpenAICompatibleClient, MiniMaxSettings))
    client = client_class(settings_class(api_key="fake", base_url="https://example.invalid", model_name="configured",
                                         max_retries=1, streaming_enabled=False), Transport(), logger, budget)
    client.chat(request())
    assert len(calls) == 2
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == 1
    starts = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
    ends = JsonlStore(validator).read_all(run / "model_calls.jsonl", "model_call")
    assert len(starts) == len(ends) == 1 and starts[0]["request_attempt_id"] == ends[0]["request_attempt_id"]


def test_route_fallback_has_separate_preparations_and_preserves_unknown_failure_usage(tmp_path):
    from asteria_runtime.models.routing import RoutedModelClient
    validator, policy, run, budget, logger = setup(tmp_path)

    class Timeout:
        def chat(self, req):
            raise TimeoutError("deadline exceeded")

    class Good:
        def chat(self, req):
            return response()

    strong = MeteredModelClient(Timeout(), budget, logger)
    medium = MeteredModelClient(Good(), budget, logger)
    RoutedModelClient(medium, {"strong": strong}, {}).chat(request())
    starts = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")
    ends = JsonlStore(validator).read_all(run / "model_calls.jsonl", "model_call")
    assert [r["model_tier"] for r in starts] == ["strong", "medium"]
    assert len({r["request_attempt_id"] for r in starts}) == 2
    assert [r["request_attempt_id"] for r in starts] == [r["request_attempt_id"] for r in ends]
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == 2 and report["estimated_input_tokens"] is None
    assert report["accounting_recovery"]["unresolved_model_requests"] == 0
    assert report["accounting_recovery"]["known_input_tokens_lower_bound"] == 10


def test_prepared_schema_rejects_raw_content_and_invented_dispatch(tmp_path):
    from asteria_runtime.storage.schema_validator import SchemaValidationError
    validator, _, run, _, logger = setup(tmp_path)
    logger.record_prepared(request(), "provider", "model")
    row = JsonlStore(validator).read_all(run / "model_request_attempts.jsonl", "model_request_attempt")[0]
    for extra in ({"raw_messages": []}, {"dispatch_state": "sent"}, {"status": "success"}):
        with pytest.raises(SchemaValidationError):
            validator.validate("model_request_attempt", {**row, **extra})


def test_terminal_after_recovery_closes_only_its_identity_and_updates_recovery_metadata(tmp_path):
    validator, policy, run, _, logger = setup(tmp_path)
    attempt = logger.record_prepared(request(), "provider", "model")
    pending = BudgetController.from_run(policy, run, validator).cost_report()
    assert pending["accounting_recovery"]["unresolved_model_requests"] == 1
    logger.record_success(request(), response(), request_attempt_id=attempt)
    report = BudgetController.from_run(policy, run, validator).cost_report()
    assert report["model_calls"] == 1
    assert report["accounting_recovery"]["unresolved_model_requests"] == 0
    assert report["accounting_recovery"]["unrecorded_model_attempts"] == 0
    assert report["estimated_input_tokens"] is None  # unknown high-water history is not silently refunded
    assert report["accounting_recovery"]["known_input_tokens_lower_bound"] == 10
