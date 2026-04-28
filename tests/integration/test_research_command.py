import json
from pathlib import Path

import pytest

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.research_command import ResearchCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakeResearchClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        source = payload["sources"][0]
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "query": payload["query"],
                    "created_at": "2026-04-28T10:00:00+08:00",
                    "sources": [
                        {
                            "source_id": source["source_id"],
                            "title": source["title"],
                            "source_type": source["source_type"],
                            "reference": source["reference"],
                            "summary": source["summary"],
                        }
                    ],
                    "claims": [
                        {
                            "claim": "Password tools should include multiple checks, not only length.",
                            "source_ids": [source["source_id"]],
                            "confidence": "high",
                        }
                    ],
                    "expanded_requirements": [
                        {
                            "description": "Include character diversity and common-password checks.",
                            "priority": "must",
                            "source_ids": [source["source_id"]],
                        }
                    ],
                    "risks": [
                        {
                            "risk": "Overclaiming password security.",
                            "mitigation": "Describe the result as a heuristic estimate.",
                            "source_ids": [source["source_id"]],
                        }
                    ],
                    "decision_candidates": [
                        {
                            "question": "Should the first version be CLI or Web UI?",
                            "options": [
                                {"option_id": "cli", "label": "CLI", "tradeoff": "lower scope"},
                                {"option_id": "web", "label": "Web UI", "tradeoff": "better UX"},
                            ],
                            "recommended_option_id": "cli",
                        }
                    ],
                    "summary": "Research found practical password-tool requirements.",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-research",
            raw_response={},
        )


def test_research_command_collects_local_sources_and_writes_reports(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "password.md").write_text(
        "Password tools should check length, character diversity, and common passwords.\n",
        encoding="utf-8",
    )

    result = ResearchCommand(
        tmp_path,
        "password tool requirements",
        model_client=FakeResearchClient(),
    ).run()

    assert result.source_count == 1
    assert result.claim_count == 1
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["claims"][0]["source_ids"] == ["local-0001"]
    assert "character diversity" in result.markdown_path.read_text(encoding="utf-8")
    run_dir = tmp_path / ".agent" / "runs" / result.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "Research report created" in events
    cost = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost["research_calls"] == 1
    assert cost["model_calls"] == 1


def test_research_command_rejects_url_sources_when_network_disabled(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    with pytest.raises(PermissionError):
        ResearchCommand(
            tmp_path,
            "external topic",
            urls=["https://example.com"],
            use_local=False,
            model_client=FakeResearchClient(),
        ).run()
