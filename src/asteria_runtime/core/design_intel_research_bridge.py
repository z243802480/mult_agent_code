from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from asteria_runtime.core.design_intel_contract import (
    apply_research_type_to_goal_spec,
    map_research_cli_type_to_plan_type,
    research_cli_types,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


DESIGN_INTEL_RESEARCH_EVIDENCE_FILE = "design_intel_research_evidence.json"
RESEARCH_REPORT_FILENAME = "research_report.json"


class ModelClient(Protocol):
    def chat(self, request: Any) -> Any: ...


class BridgeResearchClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        source = payload["sources"][0]
        research_type = payload.get("research_type", "general")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "query": payload["query"],
                    "research_type": research_type,
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
                    "risks": [],
                    "decision_candidates": [],
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


class BridgePlanClient:
    def __init__(self, *, normalized_goal: str) -> None:
        self.normalized_goal = normalized_goal

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": self.normalized_goal,
                    "normalized_goal": self.normalized_goal,
                    "goal_type": "research",
                    "assumptions": ["Plan follows linked research report."],
                    "constraints": ["local_first"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": self.normalized_goal,
                            "source": "user",
                            "acceptance": ["Plan reflects research-backed requirements"],
                        }
                    ],
                    "target_outputs": ["report.md"],
                    "definition_of_done": ["Research-backed plan exists"],
                    "verification_strategy": ["manual_review"],
                    "budget": {"max_iterations": 4, "max_model_calls": 20},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


@dataclass(frozen=True)
class DesignIntelResearchBandResult:
    ok: bool
    run_id: str
    run_dir: Path
    research_cli_type: str
    plan_research_type: str | None
    research_profile_dispatched: bool
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "research_cli_type": self.research_cli_type,
            "plan_research_type": self.plan_research_type,
            "research_profile_dispatched": self.research_profile_dispatched,
            "summary": self.summary,
        }


def research_report_path(run_dir: Path) -> Path:
    return run_dir / RESEARCH_REPORT_FILENAME


def load_research_report(run_dir: Path, validator: SchemaValidator) -> dict[str, Any] | None:
    path = research_report_path(run_dir)
    if not path.exists():
        return None
    store = JsonStore(validator)
    report = store.read(path, "research_report")
    return report if isinstance(report, dict) else None


def build_research_runtime_context(
    report: dict[str, Any],
    report_path: Path,
) -> dict[str, Any]:
    cli_type = str(report.get("research_type") or "general")
    return {
        "report_path": str(report_path),
        "query": str(report.get("query") or ""),
        "summary": str(report.get("summary") or ""),
        "research_cli_type": cli_type,
        "plan_research_type": map_research_cli_type_to_plan_type(cli_type),
        "claim_count": len(report.get("claims") or []),
        "source_count": len(report.get("sources") or []),
        "expanded_requirements": [
            {
                "description": str(item.get("description") or ""),
                "priority": str(item.get("priority") or "should"),
            }
            for item in (report.get("expanded_requirements") or [])[:8]
            if isinstance(item, dict) and str(item.get("description") or "").strip()
        ],
        "design_brief": report.get("design_brief")
        if isinstance(report.get("design_brief"), dict)
        else {},
    }


def apply_research_report_bridge(
    goal_spec: dict[str, Any],
    report: dict[str, Any],
    *,
    report_path: str,
) -> dict[str, Any]:
    result = dict(goal_spec)
    cli_type = str(report.get("research_type") or "general").strip().lower()
    if cli_type:
        result["research_cli_type"] = cli_type
    if report_path:
        result["research_report_ref"] = report_path

    merged = list(result.get("expanded_requirements") or [])
    existing_descriptions = {
        str(item.get("description") or "").strip().lower()
        for item in merged
        if isinstance(item, dict)
    }
    next_index = len(merged) + 1
    for item in report.get("expanded_requirements") or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description or description.lower() in existing_descriptions:
            continue
        priority = str(item.get("priority") or "should").strip().lower()
        if priority not in {"must", "should", "could", "wont"}:
            priority = "should"
        merged.append(
            {
                "id": f"req-research-{next_index:04d}",
                "priority": priority,
                "description": description,
                "source": "research",
                "acceptance": [
                    f"Research-backed requirement is reflected in the plan: {description}"
                ],
            }
        )
        existing_descriptions.add(description.lower())
        next_index += 1
    result["expanded_requirements"] = merged

    summary = str(report.get("summary") or "").strip()
    if summary:
        assumptions = list(result.get("assumptions") or [])
        note = f"Research report ({cli_type}) informs this plan: {summary}"
        if note not in assumptions:
            assumptions.append(note)
        result["assumptions"] = assumptions

    return apply_research_type_to_goal_spec(result)


def find_design_intel_research_evidence(root: Path) -> dict[str, Any] | None:
    runs_root = root / ".asteria" / "runs"
    if not runs_root.is_dir():
        return None
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        path = run_dir / DESIGN_INTEL_RESEARCH_EVIDENCE_FILE
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def run_design_intel_research_band(
    root: Path,
    validator: SchemaValidator,
    *,
    research_client: ModelClient | None = None,
    plan_client: ModelClient | None = None,
    research_type: str = "product_research",
    goal: str = "Build a password tool informed by product research",
) -> DesignIntelResearchBandResult:
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.commands.plan_command import PlanCommand
    from asteria_runtime.commands.research_command import ResearchCommand

    root.mkdir(parents=True, exist_ok=True)
    InitCommand(root).run()
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "password-research.md").write_text(
        "Password tools should check length, character diversity, and common passwords.\n",
        encoding="utf-8",
    )

    research = ResearchCommand(
        root,
        "password tool requirements",
        research_type=research_type,
        model_client=research_client or BridgeResearchClient(),
    ).run()
    run_dir = root / ".asteria" / "runs" / research.run_id
    plan = PlanCommand(
        root,
        goal,
        run_id=research.run_id,
        model_client=plan_client or BridgePlanClient(normalized_goal=goal),
    ).run()

    goal_spec = json.loads(plan.goal_spec_path.read_text(encoding="utf-8"))
    loop_dispatch = json.loads((run_dir / "agent_loop_dispatch.json").read_text(encoding="utf-8"))
    profile_counts = loop_dispatch.get("profile_counts") or {}
    research_profile_dispatched = int(profile_counts.get("research") or 0) > 0 or any(
        str(item.get("loop_profile_id") or "") == "research"
        for item in loop_dispatch.get("task_dispatch") or []
        if isinstance(item, dict)
    )

    plan_research_type = goal_spec.get("research_type")
    ok = (
        goal_spec.get("research_cli_type") == research_type
        and plan_research_type == "research"
        and bool(goal_spec.get("research_report_ref"))
        and any(
            str(item.get("source") or "") == "research"
            for item in goal_spec.get("expanded_requirements") or []
            if isinstance(item, dict)
        )
        and research_profile_dispatched
    )
    evidence = {
        "schema_version": "0.1.0",
        "recorded_at": now_iso(),
        "ok": ok,
        "run_id": research.run_id,
        "research_cli_type": research_type,
        "plan_research_type": plan_research_type,
        "research_profile_dispatched": research_profile_dispatched,
        "profile_research_evidence": "design_intel_research_band",
        "summary": "Design Intel research bridge passed." if ok else "Design Intel research bridge blocked.",
    }
    JsonStore(validator).write(
        run_dir / DESIGN_INTEL_RESEARCH_EVIDENCE_FILE,
        evidence,
        schema_name=None,
    )
    return DesignIntelResearchBandResult(
        ok=ok,
        run_id=research.run_id,
        run_dir=run_dir,
        research_cli_type=research_type,
        plan_research_type=str(plan_research_type) if plan_research_type else None,
        research_profile_dispatched=research_profile_dispatched,
        summary=str(evidence["summary"]),
    )


def bridge_scope_cli_types() -> tuple[str, ...]:
    return research_cli_types()
