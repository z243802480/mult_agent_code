from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class RoadmapResult:
    root: Path
    roadmap_path: Path
    markdown_path: Path
    status: str
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "roadmap_path": str(self.roadmap_path),
            "markdown_path": str(self.markdown_path),
            "status": self.status,
            "next_actions": self.next_actions,
            "control_surface": control_surface_contract(
                command="roadmap-update",
                audience="maintainer_ops_reporting",
                stable_fields=[
                    "schema_version",
                    "root",
                    "roadmap_path",
                    "markdown_path",
                    "status",
                    "next_actions",
                ],
            ),
        }

    def to_text(self) -> str:
        lines = [
            "Project roadmap updated",
            f"Status: {self.status}",
            f"Roadmap: {self.roadmap_path}",
            f"Markdown: {self.markdown_path}",
        ]
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"  - {item}" for item in self.next_actions)
        return "\n".join(lines)


class RoadmapCommand:
    def __init__(self, root: Path, *, output: Path | None = None) -> None:
        self.root = root.resolve()
        self.output = output
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> RoadmapResult:
        agent_dir = self.root / ".asteria"
        roadmap = self._roadmap(agent_dir)
        roadmap_path = agent_dir / "product" / "project_roadmap.json"
        markdown_path = self.output or self.root / "docs" / "zh" / "自动路线图.md"
        self.store.write(roadmap_path, roadmap, "project_roadmap")
        self._write_markdown(markdown_path, roadmap)
        return RoadmapResult(
            root=self.root,
            roadmap_path=roadmap_path,
            markdown_path=markdown_path,
            status=str(roadmap["status"]),
            next_actions=[str(item) for item in roadmap["next_actions"]],
        )

    def _roadmap(self, agent_dir: Path) -> dict[str, Any]:
        weekly = self._latest_weekly_report(agent_dir)
        acceptance = weekly.get("acceptance") if weekly else {}
        acceptance = acceptance if isinstance(acceptance, dict) else {}
        model_profile = weekly.get("model_profile") if weekly else self._model_profile(agent_dir)
        model_profile = model_profile if isinstance(model_profile, dict) else {}
        risks = [str(item) for item in weekly.get("risks", [])] if weekly else []
        next_actions = [str(item) for item in weekly.get("next_actions", [])] if weekly else []
        usage_signals = weekly.get("usage_signals") if weekly else {}
        usage_signals = usage_signals if isinstance(usage_signals, dict) else {}
        usage_analysis = weekly.get("usage_signal_analysis") if weekly else {}
        usage_analysis = usage_analysis if isinstance(usage_analysis, dict) else {}
        effective_usage_signals = _effective_usage_signals(usage_signals, usage_analysis)
        risks = _effective_risks(risks, effective_usage_signals, usage_analysis)
        next_actions = _effective_next_actions(next_actions, effective_usage_signals, usage_analysis)
        capabilities = self._capabilities(acceptance, model_profile)
        milestones = self._milestones(acceptance, model_profile, risks, effective_usage_signals, usage_analysis)
        for task in usage_analysis.get("roadmap_tasks", [])[:3]:
            if isinstance(task, dict):
                next_actions.append(str(task.get("title") or task.get("task_id")))
        if not weekly:
            next_actions.append(
                "Run `asteria daily-plan --objective <goal>` to start evidence collection."
            )
            next_actions.append("Run `asteria /weekly-report` before the next roadmap update.")
        if not next_actions:
            next_actions = [item["goal"] for item in milestones if item["status"] != "done"][:3]
        next_actions = list(dict.fromkeys(next_actions))
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "created_at": now_iso(),
            "status": self._status(risks, acceptance),
            "product_brief": (
                "Build a local-first multi-agent autonomous development runtime that turns "
                "compact goals into verified artifacts through planning, execution, repair, "
                "acceptance gates, model capability learning, and production reporting."
            ),
            "current_capabilities": capabilities,
            "open_risks": risks,
            "milestones": milestones,
            "next_actions": next_actions,
            "source_reports": {
                "weekly_report": weekly.get("report_path") if weekly else None,
                "acceptance_suite": acceptance.get("latest_suite"),
                "model_profile_status": model_profile.get("status"),
                "usage_signal_status": effective_usage_signals.get("status"),
                "usage_signal_analysis_status": usage_analysis.get("status"),
                "dogfooding_gate_status": _dogfooding_gate(usage_analysis).get("status"),
            },
        }

    def _latest_weekly_report(self, agent_dir: Path) -> dict[str, Any]:
        reports_dir = agent_dir / "reports"
        if not reports_dir.exists():
            return {}
        reports = sorted(reports_dir.glob("weekly_report_*.json"))
        if not reports:
            return {}
        path = reports[-1]
        report = self.store.read(path, "weekly_report")
        report["report_path"] = str(path)
        return report

    def _model_profile(self, agent_dir: Path) -> dict[str, Any]:
        path = agent_dir / "model" / "capability_profile.json"
        if not path.exists():
            return {"status": "missing", "profile_count": 0, "weak_routes": []}
        profile = self.store.read(path, "model_capability_profile")
        weak_routes = [
            item
            for item in profile.get("profiles", [])
            if isinstance(item, dict)
            and int(item.get("total_calls") or 0) >= 2
            and float(item.get("success_rate") or 0.0) < 0.8
        ]
        return {
            "status": "ready",
            "profile_count": int(profile.get("profile_count") or 0),
            "weak_routes": weak_routes[:10],
        }

    def _capabilities(self, acceptance: dict[str, Any], model_profile: dict[str, Any]) -> list[str]:
        capabilities = [
            "Long-run cycles can be planned, budgeted, paused, and reported.",
            "Acceptance failures can be promoted into targeted repair tasks.",
            "Weekly production reporting summarizes progress, risks, and next actions.",
        ]
        if acceptance.get("latest_failed", 0):
            capabilities.append("Acceptance gate has known failing scenarios that require repair.")
        else:
            capabilities.append("Latest acceptance state has no reported failures.")
        if model_profile.get("status") == "ready":
            capabilities.append("Model capability profile is available for routing decisions.")
        else:
            capabilities.append("Model capability profile still needs runtime data.")
        return capabilities

    def _milestones(
        self,
        acceptance: dict[str, Any],
        model_profile: dict[str, Any],
        risks: list[str],
        usage_signals: dict[str, Any],
        usage_analysis: dict[str, Any],
    ) -> list[dict[str, str]]:
        acceptance_done = not acceptance.get("latest_failed", 0)
        model_done = model_profile.get("status") == "ready" and not model_profile.get("weak_routes")
        dogfooding_gate = _dogfooding_gate(usage_analysis)
        if dogfooding_gate:
            ops_done = bool(dogfooding_gate.get("ready_for_next_batch"))
        else:
            ops_done = usage_signals.get("status") in {"healthy", "missing"} and not usage_signals.get(
                "unresolved", 0
            )
        return [
            {
                "id": "M1",
                "goal": "Keep core long-run loop reliable and bounded.",
                "status": "done" if not risks else "in_progress",
                "evidence": "weekly-report and long-run report",
            },
            {
                "id": "M2",
                "goal": "Close remaining real acceptance failures with targeted repairs.",
                "status": "done" if acceptance_done else "blocked",
                "evidence": "acceptance_report.json",
            },
            {
                "id": "M3",
                "goal": "Use model capability data to guide routing safely.",
                "status": "done" if model_done else "in_progress",
                "evidence": "capability_profile.json",
            },
            {
                "id": "M4",
                "goal": "Automate project Roadmap and PRD updates from runtime evidence.",
                "status": "done",
                "evidence": "project_roadmap.json and docs/zh/自动路线图.md",
            },
            {
                "id": "M5",
                "goal": "Use background usage signals to steer dogfooding without changing the user workflow.",
                "status": "done" if ops_done else "in_progress",
                "evidence": "ops/usage_signals.jsonl and weekly_report usage_signals",
            },
        ]

    def _status(self, risks: list[str], acceptance: dict[str, Any]) -> str:
        if acceptance.get("latest_failed", 0):
            return "blocked"
        if risks:
            return "needs_attention"
        return "on_track"

    def _write_markdown(self, path: Path, roadmap: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# 自动路线图",
            "",
            f"- 状态：{roadmap['status']}",
            f"- 更新时间：{roadmap['created_at']}",
            "",
            "## 产品简述",
            "",
            roadmap["product_brief"],
            "",
            "## 当前能力",
            "",
        ]
        lines.extend(f"- {item}" for item in roadmap["current_capabilities"])
        lines.extend(["", "## 里程碑", ""])
        for item in roadmap["milestones"]:
            lines.append(f"- {item['id']} [{item['status']}]: {item['goal']} ({item['evidence']})")
        lines.extend(["", "## 风险", ""])
        lines.extend(f"- {item}" for item in roadmap["open_risks"] or ["暂无开放风险"])
        lines.extend(["", "## 下一步", ""])
        lines.extend(f"- {item}" for item in roadmap["next_actions"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _effective_usage_signals(
    usage_signals: dict[str, Any],
    usage_analysis: dict[str, Any],
) -> dict[str, Any]:
    active = usage_analysis.get("active_summary") if isinstance(usage_analysis, dict) else {}
    return active if isinstance(active, dict) and active else usage_signals


def _effective_risks(
    risks: list[str],
    usage_signals: dict[str, Any],
    usage_analysis: dict[str, Any],
) -> list[str]:
    filtered = []
    has_priority = bool(usage_analysis.get("priority_items"))
    usage_healthy = usage_signals.get("status") in {"healthy", "missing"}
    dogfooding_gate = _dogfooding_gate(usage_analysis)
    for risk in risks:
        if usage_healthy and risk.startswith("Background usage signals need review:"):
            continue
        if not has_priority and risk.startswith("Usage signal analysis has priority item"):
            continue
        filtered.append(risk)
    if dogfooding_gate.get("status") == "blocked":
        filtered.append("Dogfooding gate is blocked: " + str(dogfooding_gate.get("reason") or ""))
    return filtered


def _effective_next_actions(
    actions: list[str],
    usage_signals: dict[str, Any],
    usage_analysis: dict[str, Any],
) -> list[str]:
    filtered = []
    has_tasks = bool(usage_analysis.get("roadmap_tasks"))
    usage_healthy = usage_signals.get("status") in {"healthy", "missing"}
    dogfooding_gate = _dogfooding_gate(usage_analysis)
    for action in actions:
        if usage_healthy and "ops-signal --summary" in action:
            continue
        if not has_tasks and "usage_signal_analysis.json" in action:
            continue
        filtered.append(action)
    if dogfooding_gate.get("status") in {"missing", "collecting"}:
        filtered.append(str(dogfooding_gate.get("reason") or "Collect scoped dogfooding signals."))
    elif dogfooding_gate.get("status") == "blocked":
        filtered.append("Resolve dogfooding gate blockers before the next scoped batch.")
    elif dogfooding_gate.get("status") == "ready":
        next_batch_plan = _next_batch_plan(usage_analysis)
        if next_batch_plan.get("status") == "completed":
            filtered.append(
                "Alpha.2 next scoped dogfooding batch is complete; "
                "review the fresh evidence bundle and choose the next gated development lane."
            )
        elif next_batch_plan.get("ready"):
            batch_id = str(next_batch_plan.get("batch_id") or "next scoped batch")
            max_tasks = int(next_batch_plan.get("max_tasks") or 0)
            task_count = len(next_batch_plan.get("task_candidates") or [])
            filtered.append(
                f"Run `{batch_id}`: at most {max_tasks} scoped task(s) "
                f"from {task_count} candidate(s), then bind results to usage signals."
            )
        else:
            filtered.append("Dogfooding gate is ready; run the next scoped validation batch.")
    return filtered


def _dogfooding_gate(usage_analysis: dict[str, Any]) -> dict[str, Any]:
    gate = usage_analysis.get("dogfooding_gate") if isinstance(usage_analysis, dict) else {}
    return gate if isinstance(gate, dict) else {}


def _next_batch_plan(usage_analysis: dict[str, Any]) -> dict[str, Any]:
    plan = usage_analysis.get("next_batch_plan") if isinstance(usage_analysis, dict) else {}
    return plan if isinstance(plan, dict) else {}
