from __future__ import annotations

import json
from dataclasses import dataclass

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from agent_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator
from agent_runtime.utils.time import now_iso


class ResearchAgentError(RuntimeError):
    pass


@dataclass
class ResearchAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def synthesize(self, query: str, sources: list[dict], run_id: str | None) -> dict:
        request = ChatRequest(
            purpose="research_synthesis",
            model_tier="strong",
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=self._user_prompt(query, sources, run_id)),
            ],
            response_format="json",
            temperature=0.15,
            max_output_tokens=6000,
            metadata={"run_id": run_id, "agent_id": "ResearchAgent"},
        )
        response = self.model_client.chat(request)
        report = self._parse_json(response.content)
        report.setdefault("schema_version", "0.1.0")
        report.setdefault("run_id", run_id)
        report.setdefault("query", query)
        report.setdefault("created_at", now_iso())
        try:
            self.validator.validate("research_report", report)
        except SchemaValidationError as exc:
            raise ResearchAgentError(f"ResearchReport failed schema validation: {exc}") from exc
        return report

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise ResearchAgentError(f"Research response was not valid JSON: {exc}") from exc
        return parsed

    def _system_prompt(self) -> str:
        return """You are ResearchAgent for an autonomous development runtime.

Return only valid JSON matching the ResearchReport schema. Do not wrap in markdown.

Rules:
- Use only supplied sources as evidence.
- Every factual claim must cite source_ids.
- Clearly separate sourced claims from inferred requirements.
- Convert findings into product/engineering requirements, risks, and decision candidates.
- Prefer practical implementation guidance over generic summaries.
- If evidence is weak, mark confidence as low and say what is missing.
"""

    def _user_prompt(self, query: str, sources: list[dict], run_id: str | None) -> str:
        payload = {
            "run_id": run_id,
            "query": query,
            "sources": sources,
            "required_output_shape": {
                "schema_version": "0.1.0",
                "run_id": run_id,
                "query": query,
                "created_at": "ISO-8601 timestamp",
                "sources": [
                    {
                        "source_id": "local-0001",
                        "title": "source title",
                        "source_type": "local|url|search",
                        "reference": "path or URL",
                        "summary": "brief summary",
                    }
                ],
                "claims": [
                    {
                        "claim": "evidence-backed finding",
                        "source_ids": ["local-0001"],
                        "confidence": "low|medium|high",
                    }
                ],
                "expanded_requirements": [
                    {
                        "description": "actionable requirement inferred from research",
                        "priority": "must|should|could",
                        "source_ids": ["local-0001"],
                    }
                ],
                "risks": [
                    {
                        "risk": "risk discovered during research",
                        "mitigation": "mitigation",
                        "source_ids": ["local-0001"],
                    }
                ],
                "decision_candidates": [
                    {
                        "question": "decision to ask user",
                        "options": [],
                        "recommended_option_id": "option-1",
                    }
                ],
                "summary": "research summary",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
