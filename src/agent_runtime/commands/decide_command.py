from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.core.budget import BudgetController
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class DecideResult:
    run_id: str
    action: str
    decisions_path: Path
    decisions: list[dict] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"Decision action: {self.action}", f"Run: {self.run_id}", f"Decisions: {self.decisions_path}"]
        for decision in self.decisions:
            lines.append(f"- {decision['decision_id']} [{decision['status']}]: {decision['question']}")
            selected = decision.get("selected_option_id") or decision.get("default_option_id")
            lines.append(f"  selected/default: {selected}")
        return "\n".join(lines)


class DecideCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        question: str | None = None,
        options_json: str | None = None,
        recommended_option_id: str | None = None,
        default_option_id: str | None = None,
        impact_json: str | None = None,
        decision_id: str | None = None,
        select_option_id: str | None = None,
        use_default: bool = False,
        list_pending: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.question = question
        self.options_json = options_json
        self.recommended_option_id = recommended_option_id
        self.default_option_id = default_option_id
        self.impact_json = impact_json
        self.decision_id = decision_id
        self.select_option_id = select_option_id
        self.use_default = use_default
        self.list_pending = list_pending
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> DecideResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        run_id = self.run_id or self._latest_run_id(agent_dir)
        if not run_id:
            raise RuntimeError("No run found. Run `agent plan` first.")
        run_dir = RunStore(agent_dir, self.validator).run_dir(run_id)
        decisions_path = run_dir / "decisions.jsonl"

        if self.list_pending:
            pending = [decision for decision in self._read_decisions(decisions_path) if decision["status"] == "pending"]
            return DecideResult(run_id, "list_pending", decisions_path, pending)

        if self.select_option_id or self.use_default:
            decision = self._resolve_decision(agent_dir, run_dir, decisions_path, run_id)
            return DecideResult(run_id, "resolve", decisions_path, [decision])

        decision = self._create_decision(agent_dir, run_dir, decisions_path, run_id)
        return DecideResult(run_id, "create", decisions_path, [decision])

    def _create_decision(self, agent_dir: Path, run_dir: Path, decisions_path: Path, run_id: str) -> dict:
        if not self.question:
            raise ValueError("question is required when creating a decision")
        options = self._parse_options()
        if len(options) < 2 or len(options) > 4:
            raise ValueError("decision options must contain 2 to 4 options")
        option_ids = {option["option_id"] for option in options}
        recommended = self.recommended_option_id or options[0]["option_id"]
        default = self.default_option_id or recommended
        if recommended not in option_ids:
            raise ValueError(f"recommended option not found: {recommended}")
        if default not in option_ids:
            raise ValueError(f"default option not found: {default}")
        decision = {
            "schema_version": "0.1.0",
            "decision_id": self.decision_id or self._next_decision_id(decisions_path),
            "status": "pending",
            "question": self.question,
            "recommended_option_id": recommended,
            "options": options,
            "default_option_id": default,
            "impact": self._parse_impact(),
            "selected_option_id": None,
            "created_at": now_iso(),
            "resolved_at": None,
        }
        self.validator.validate("decision_point", decision)
        self.jsonl.append(decisions_path, decision, "decision_point")
        self._record_event(run_dir, run_id, "decision_created", decision["question"], {"decision_id": decision["decision_id"]})
        self._record_user_decision_cost(agent_dir, run_dir, run_id)
        return decision

    def _resolve_decision(self, agent_dir: Path, run_dir: Path, decisions_path: Path, run_id: str) -> dict:
        if not self.decision_id:
            raise ValueError("decision_id is required when resolving a decision")
        decisions = self._read_decisions(decisions_path)
        resolved = None
        for decision in decisions:
            if decision["decision_id"] != self.decision_id:
                continue
            if decision["status"] != "pending":
                raise ValueError(f"decision is not pending: {self.decision_id}")
            option_id = decision["default_option_id"] if self.use_default else self.select_option_id
            if option_id not in {option["option_id"] for option in decision["options"]}:
                raise ValueError(f"option not found: {option_id}")
            decision["status"] = "defaulted" if self.use_default else "resolved"
            decision["selected_option_id"] = option_id
            decision["resolved_at"] = now_iso()
            self.validator.validate("decision_point", decision)
            resolved = decision
            break
        if resolved is None:
            raise ValueError(f"decision not found: {self.decision_id}")
        self._rewrite_decisions(decisions_path, decisions)
        self._record_event(
            run_dir,
            run_id,
            "decision_resolved",
            f"{resolved['decision_id']} -> {resolved['selected_option_id']}",
            {"decision_id": resolved["decision_id"], "selected_option_id": resolved["selected_option_id"]},
        )
        self._record_user_decision_cost(agent_dir, run_dir, run_id)
        return resolved

    def _parse_options(self) -> list[dict]:
        if not self.options_json:
            raise ValueError("options_json is required")
        parsed = json.loads(self.options_json)
        if not isinstance(parsed, list):
            raise ValueError("options_json must be a JSON array")
        return parsed

    def _parse_impact(self) -> dict:
        if not self.impact_json:
            return {"scope": "medium", "budget": "medium", "risk": "medium", "quality": "medium"}
        parsed = json.loads(self.impact_json)
        if not isinstance(parsed, dict):
            raise ValueError("impact_json must be a JSON object")
        return parsed

    def _read_decisions(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return self.jsonl.read_all(path, "decision_point")

    def _rewrite_decisions(self, path: Path, decisions: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(decision, ensure_ascii=False) for decision in decisions)
        path.write_text(content + ("\n" if content else ""), encoding="utf-8")

    def _record_event(self, run_dir: Path, run_id: str, event_type: str, summary: str, data: dict) -> None:
        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            event_type,
            "DecideCommand",
            summary,
            data,
        )

    def _record_user_decision_cost(self, agent_dir: Path, run_dir: Path, run_id: str) -> None:
        policy = self.store.read(agent_dir / "policies.json", "policy_config")
        cost_path = run_dir / "cost_report.json"
        report = self._read_cost(cost_path, run_id)
        budget = BudgetController.from_report(policy, report, run_id=run_id)
        budget.record_user_decision()
        self.store.write(cost_path, budget.cost_report(), "cost_report")

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
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }

    def _next_decision_id(self, path: Path) -> str:
        return f"decision-{len(self._read_decisions(path)) + 1:04d}"

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted([path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name)
        return runs[-1].name if runs else None
