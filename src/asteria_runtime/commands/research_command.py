from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.agents.research_agent import ResearchAgent
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.research.sources import (
    LocalDocumentSource,
    ResearchSourceRecord,
    SerperSearchSource,
    UrlSource,
)
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ResearchResult:
    run_id: str
    report_path: Path
    markdown_path: Path
    source_count: int
    claim_count: int
    research_type: str = "general"

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Research run: {self.run_id}",
                f"Type: {self.research_type}",
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
        research_type: str = "general",
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.query = query
        self.run_id = run_id
        self.urls = urls or []
        self.use_local = use_local
        self.use_serper = use_serper
        self.max_sources = max_sources
        self.research_type = research_type
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> ResearchResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
        policy = load_policy_config(agent_dir, self.validator)
        run_store = RunStore(agent_dir, self.validator)
        run = (
            run_store.load_run(self.run_id)
            if self.run_id
            else run_store.create_run(f'asteria research "{self.query}"')
        )
        run_id = run["run_id"]
        run_dir = run_store.run_dir(run_id)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(
            policy, self._read_cost(cost_report_path, run_id), run_id=run_id
        )
        budget.record_research_call()
        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)

        run["status"] = "running"
        run["current_phase"] = "RESEARCH"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ResearchCommand", "INIT -> RESEARCH")
        progress.record(
            run_id=run_id,
            channel="progress",
            phase="plan",
            status="running",
            title="开始研究",
            summary=f"正在围绕“{self.query}”收集本地或授权来源。",
            display_level="main",
            call_chain=["ResearchCommand"],
            execution_chain=["research", "source_collection"],
        )

        try:
            source_records = self._collect_sources(policy)
        except Exception as exc:
            progress.record(
                run_id=run_id,
                channel="progress",
                phase="blocked",
                status="blocked",
                title="研究来源受阻",
                summary=str(exc),
                display_level="main",
                call_chain=["ResearchCommand"],
                execution_chain=["research", "source_collection"],
            )
            raise
        source_payload = [
            self._source_payload(record) for record in source_records[: self.max_sources]
        ]
        if not source_payload:
            progress.record(
                run_id=run_id,
                channel="progress",
                phase="blocked",
                status="blocked",
                title="没有可用研究来源",
                summary="未收集到本地文档、URL 或可用搜索结果，无法生成研究报告。",
                display_level="main",
                call_chain=["ResearchCommand"],
                execution_chain=["research", "source_collection"],
            )
            raise RuntimeError(
                "No research sources were collected. Provide local docs, URLs, or SERPER_API_KEY."
            )
        progress.record(
            run_id=run_id,
            channel="evidence",
            event_type="evidence",
            phase="plan",
            status="completed",
            title="研究来源已收集",
            summary=f"已收集 {len(source_payload)} 个来源，准备综合研究结论。",
            display_level="inspector",
            data={
                "source_count": len(source_payload),
                "source_refs": [source["reference"] for source in source_payload],
            },
            call_chain=["ResearchCommand"],
            execution_chain=["research", "sources"],
        )

        agent = ResearchAgent(self._model_client(run_dir, budget), self.validator)
        progress.record(
            run_id=run_id,
            channel="progress",
            phase="review",
            status="running",
            title="正在综合研究结论",
            summary="研究智能体正在分析来源、提取结论、要求和风险。",
            display_level="main",
            call_chain=["ResearchCommand", "ResearchAgent"],
            execution_chain=["research", "synthesis"],
        )
        report = agent.synthesize(
            self.query,
            source_payload,
            run_id,
            research_type=self.research_type,
        )
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
        progress.artifact_event(
            run_id=run_id,
            title="研究报告已写入",
            summary=(
                f"研究报告包含 {len(report['sources'])} 个来源、"
                f"{len(report['claims'])} 条结论。"
            ),
            artifact_refs=[str(report_path), str(markdown_path)],
            phase="result",
        )
        progress.conclusion(
            run_id=run_id,
            phase="result",
            title="研究完成",
            summary=report["summary"],
            artifact_refs=[str(report_path), str(markdown_path)],
        )
        return ResearchResult(
            run_id=run_id,
            report_path=report_path,
            markdown_path=markdown_path,
            source_count=len(report["sources"]),
            claim_count=len(report["claims"]),
            research_type=str(report.get("research_type") or self.research_type),
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
            return MeteredModelClient(
                self.model_client, budget, ModelCallLogger(run_dir, self.validator)
            )
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
            f"- Type: {report.get('research_type', 'general')}",
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
        design_brief = report.get("design_brief")
        if isinstance(design_brief, dict):
            lines.extend(["", "## Design Brief", ""])
            problem = str(design_brief.get("problem") or "").strip()
            if problem:
                lines.append(f"- Problem: {problem}")
            for key, label in (
                ("observed_patterns", "Observed patterns"),
                ("asteria_adaptation", "Asteria adaptation"),
                ("do_not_copy", "Do not copy"),
                ("open_questions", "Open questions"),
            ):
                values = design_brief.get(key)
                if isinstance(values, list) and values:
                    lines.append(f"- {label}: " + "; ".join(str(item) for item in values))
        patterns = report.get("pattern_candidates")
        if isinstance(patterns, list) and patterns:
            lines.extend(["", "## Pattern Candidates", ""])
            for pattern in patterns:
                if not isinstance(pattern, dict):
                    continue
                name = str(pattern.get("name") or "Unnamed pattern")
                adaptation = str(pattern.get("asteria_adaptation") or "").strip()
                validation = str(pattern.get("validation") or "").strip()
                line = f"- {name}"
                if adaptation:
                    line += f": {adaptation}"
                if validation:
                    line += f" Validate with: {validation}"
                lines.append(line)
        return "\n".join(lines) + "\n"
