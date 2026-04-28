from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.agents.research_agent import ResearchAgent
from agent_runtime.core.budget import BudgetController
from agent_runtime.models.base import ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.metered import MeteredModelClient
from agent_runtime.models.model_call_logger import ModelCallLogger
from agent_runtime.research.sources import LocalDocumentSource, ResearchSourceRecord, SerperSearchSource, UrlSource
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ResearchResult:
    run_id: str
    report_path: Path
    markdown_path: Path
    source_count: int
    claim_count: int

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Research run: {self.run_id}",
                f"Sources: {self.source_count}",
                f"Claims: {self.claim_count}",
                f"Report: {self.report_path}",
                f"Markdown: {self.markdown_path}",
            ]
        )


class ResearchCommand:
    def __init__(
        self,
        root: Path,
        query: str,
        run_id: str | None = None,
        urls: list[str] | None = None,
        use_local: bool = True,
        use_serper: bool = False,
        max_sources: int = 12,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.query = query
        self.run_id = run_id
        self.urls = urls or []
        self.use_local = use_local
        self.use_serper = use_serper
        self.max_sources = max_sources
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> ResearchResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        run_store = RunStore(agent_dir, self.validator)
        run = run_store.load_run(self.run_id) if self.run_id else run_store.create_run(f'agent research "{self.query}"')
        run_id = run["run_id"]
        run_dir = run_store.run_dir(run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(policy, self._read_cost(cost_report_path, run_id), run_id=run_id)
        budget.record_research_call()

        run["status"] = "running"
        run["current_phase"] = "RESEARCH"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ResearchCommand", "INIT -> RESEARCH")

        source_records = self._collect_sources(policy)
        source_payload = [self._source_payload(record) for record in source_records[: self.max_sources]]
        if not source_payload:
            raise RuntimeError("No research sources were collected. Provide local docs, URLs, or SERPER_API_KEY.")

        agent = ResearchAgent(self._model_client(run_dir, budget), self.validator)
        report = agent.synthesize(self.query, source_payload, run_id)
        report["created_at"] = report.get("created_at") or now_iso()
        report_path = run_dir / "research_report.json"
        markdown_path = run_dir / "research_report.md"
        self.store.write(report_path, report, "research_report")
        markdown_path.write_text(self._markdown(report), encoding="utf-8")
        event_logger.record(
            run_id,
            "artifact_created",
            "ResearchAgent",
            f"Research report created with {len(report['claims'])} claim(s)",
            {"path": "research_report.json"},
        )
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")
        run["current_phase"] = "RESEARCHED"
        run["summary"] = report["summary"]
        run_store.update_run(run)
        return ResearchResult(
            run_id=run_id,
            report_path=report_path,
            markdown_path=markdown_path,
            source_count=len(report["sources"]),
            claim_count=len(report["claims"]),
        )

    def _collect_sources(self, policy: dict) -> list[ResearchSourceRecord]:
        records: list[ResearchSourceRecord] = []
        allow_network = bool(policy["permissions"].get("allow_network", False))
        if self.use_local:
            records.extend(
                LocalDocumentSource(
                    self.root,
                    policy["protected_paths"],
                    max_files=self.max_sources,
                ).collect(self.query)
            )
        if self.urls:
            records.extend(UrlSource(self.urls, allow_network=allow_network).collect(self.query))
        if self.use_serper:
            records.extend(
                SerperSearchSource(
                    allow_network=allow_network,
                    max_results=self.max_sources,
                ).collect(self.query)
            )
        return records[: self.max_sources]

    def _source_payload(self, record: ResearchSourceRecord) -> dict:
        return {
            "source_id": record.source_id,
            "title": record.title,
            "source_type": record.source_type,
            "reference": record.reference,
            "summary": record.summary(),
            "content": record.content,
        }

    def _model_client(self, run_dir: Path, budget: BudgetController) -> ModelClient:
        if self.model_client:
            return MeteredModelClient(self.model_client, budget, ModelCallLogger(run_dir, self.validator))
        return create_model_client(run_dir, self.validator, budget)

    def _read_cost(self, path: Path, run_id: str) -> dict:
        if path.exists():
            return self.store.read(path, "cost_report")
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "model_calls": 0,
            "tool_calls": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }

    def _markdown(self, report: dict) -> str:
        lines = [
            "# Research Report",
            "",
            f"- Query: {report['query']}",
            f"- Summary: {report['summary']}",
            "",
            "## Sources",
            "",
        ]
        for source in report["sources"]:
            lines.append(f"- [{source['source_id']}] {source['title']} ({source['reference']})")
        lines.extend(["", "## Claims", ""])
        for claim in report["claims"]:
            lines.append(f"- {claim['claim']} [{', '.join(claim['source_ids'])}]")
        lines.extend(["", "## Expanded Requirements", ""])
        for req in report["expanded_requirements"]:
            lines.append(f"- {req['priority']}: {req['description']}")
        lines.extend(["", "## Risks", ""])
        for risk in report["risks"]:
            lines.append(f"- {risk['risk']} -> {risk['mitigation']}")
        return "\n".join(lines) + "\n"
