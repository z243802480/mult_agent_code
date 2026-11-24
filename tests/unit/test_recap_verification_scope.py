"""Runtime evidence scope survives the actual recap request without test counts."""

from copy import deepcopy
import json

import pytest

from asteria_runtime.core.run_recap import author_run_recap
from tests.unit.test_run_recap import _StubModelClient


def request_for(validation):
    client = _StubModelClient("I completed the scoped work.")
    before = deepcopy(validation)
    assert (
        author_run_recap(
            model_client=client,
            goal="Finish scoped work",
            run_status="completed",
            steps=[],
            file_changes=[],
            validation=validation,
        )
        == "I completed the scoped work."
    )
    assert validation == before
    text = client.last_request.messages[-1].content
    facts = json.loads(text.split("Verification evidence scope: ")[1].splitlines()[0])
    return facts, text


@pytest.mark.parametrize(
    "scope", ["current_declared_methods_at_recorded_task_execution", "historical_records_only"]
)
def test_request_keeps_record_scope_and_history_separate(scope):
    facts, text = request_for(
        {
            "status": "passed",
            "scope": scope,
            "artifact_freshness": "unassessed",
            "requirement_coverage": "unassessed",
            "history": {"status": "failed", "total": 99999},
            "unassessed_task_ids": [],
            "total": 99999,
            "summary": "UNTRUSTED_SUMMARY",
            "command": "UNTRUSTED_COMMAND",
        }
    )
    assert "Verification status: passed" in text
    assert facts == {
        "scope": scope,
        "artifact_freshness": "unassessed",
        "requirement_coverage": "unassessed",
        "historical_execution_status": "failed",
        "unassessed_task_contracts": "none_recorded",
    }
    assert all(x not in text for x in ["99999", "UNTRUSTED_SUMMARY", "UNTRUSTED_COMMAND"])


@pytest.mark.parametrize(
    "validation",
    [
        None,
        {},
        {"status": "passed"},
        {
            "scope": "x" * 10000,
            "history": "malformed",
            "artifact_freshness": True,
            "requirement_coverage": 1,
        },
    ],
)
def test_unknown_or_invalid_fields_cannot_become_certification(validation):
    facts, text = request_for(validation)
    assert set(facts.values()) == {"unassessed"}
    assert len(text) < 1000


def test_unassessed_contract_presence_is_kept_without_task_identifiers():
    facts, text = request_for({"unassessed_task_ids": ["PRIVATE_TASK_IDENTIFIER"]})
    assert facts["unassessed_task_contracts"] == "present"
    assert "PRIVATE_TASK_IDENTIFIER" not in text
