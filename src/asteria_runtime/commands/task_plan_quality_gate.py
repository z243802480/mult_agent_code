from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.core.task_contract import completion_contract
from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class TaskPlanQualityGateResult:
    blocked: bool
    task_plan_eval: dict | None
    eval_path: Path
    decision: dict | None = None
    reason: str = ""


class TaskPlanQualityGate:
    def __init__(self, root: Path, validator: SchemaValidator) -> None:
        self.root = root.resolve()
        self.validator = validator
        self.store = JsonStore(validator)
        self.jsonl = JsonlStore(validator)

    def check(self, run_id: str, *, pause_run: bool = True) -> TaskPlanQualityGateResult:
        run_dir = self.root / ".agent" / "runs" / run_id
        eval_path = run_dir / "task_plan_eval.json"
        task_plan_eval = self.refresh(run_id, run_dir, eval_path)
        if task_plan_eval is None:
            return TaskPlanQualityGateResult(False, None, eval_path, reason="missing plan")
        if task_plan_eval["status"] != "fail":
            return TaskPlanQualityGateResult(False, task_plan_eval, eval_path, reason="quality ok")

        existing = self._quality_decisions(run_id)
        if self._quality_bypassed(existing, task_plan_eval):
            return TaskPlanQualityGateResult(
                False,
                task_plan_eval,
                eval_path,
                reason="quality bypassed by resolved decision",
            )
        if self._active_revision_task(run_id, existing):
            return TaskPlanQualityGateResult(
                False,
                task_plan_eval,
                eval_path,
                reason="active task plan revision exists",
            )
        revised_eval = self._auto_revise_once(run_id, run_dir, eval_path, task_plan_eval)
        if revised_eval and revised_eval["status"] != "fail":
            return TaskPlanQualityGateResult(
                False,
                revised_eval,
                eval_path,
                reason="quality improved by automatic replan",
            )
        if revised_eval:
            task_plan_eval = revised_eval

        pending = [decision for decision in existing if decision["status"] == "pending"]
        decision = (
            pending[0] if pending else self._create_decision(run_id, task_plan_eval, eval_path)
        )
        reason = f"Task plan quality gate paused before execution: {decision['decision_id']}."
        if pause_run:
            self._pause_run(run_id, reason)
        return TaskPlanQualityGateResult(True, task_plan_eval, eval_path, decision, reason)

    def _auto_revise_once(
        self,
        run_id: str,
        run_dir: Path,
        eval_path: Path,
        task_plan_eval: dict,
    ) -> dict | None:
        attempts_path = run_dir / "task_plan_revisions.jsonl"
        attempts = self.jsonl.read_all(attempts_path, None)
        if attempts:
            return None
        goal_spec_path = run_dir / "goal_spec.json"
        task_plan_path = run_dir / "task_plan.json"
        if not goal_spec_path.exists() or not task_plan_path.exists():
            return None
        goal_spec = self.store.read(goal_spec_path, "goal_spec")
        task_plan = self.store.read(task_plan_path, "task_board")
        revised, changes = self._revise_task_plan(task_plan, goal_spec, task_plan_eval)
        self.jsonl.append(
            attempts_path,
            {
                "schema_version": "0.1.0",
                "run_id": run_id,
                "created_at": now_iso(),
                "before_status": task_plan_eval["status"],
                "before_score": task_plan_eval["overall_score"],
                "issue_codes": self.issue_codes(task_plan_eval),
                "changes": changes,
            },
        )
        if not changes:
            return None
        self.store.write(task_plan_path, revised, "task_board")
        self.store.write(self.root / ".agent" / "tasks" / "backlog.json", revised, "task_board")
        revised_eval = TaskPlanEvaluator().evaluate(revised, goal_spec, run_id=run_id)
        self.store.write(eval_path, revised_eval, "task_plan_eval")
        return revised_eval

    def _revise_task_plan(
        self,
        task_plan: dict,
        goal_spec: dict,
        task_plan_eval: dict,
    ) -> tuple[dict, list[str]]:
        revised = json.loads(json.dumps(task_plan, ensure_ascii=False))
        tasks = [task for task in revised.get("tasks", []) if isinstance(task, dict)]
        changes: list[str] = []
        if not tasks:
            return revised, changes
        if not any(task.get("status") == "ready" for task in tasks):
            tasks[0]["status"] = "ready"
            changes.append("marked first task ready")
        known_ids = {str(task.get("task_id")) for task in tasks if task.get("task_id")}
        for task in tasks:
            original_depends = task.get("depends_on", [])
            if not isinstance(original_depends, list):
                task["depends_on"] = []
                changes.append(f"{task.get('task_id')}: normalized dependencies")
            else:
                filtered = [
                    dependency
                    for dependency in original_depends
                    if dependency in known_ids and dependency != task.get("task_id")
                ]
                if filtered != original_depends:
                    task["depends_on"] = filtered
                    changes.append(f"{task.get('task_id')}: removed invalid dependencies")
            if not task.get("acceptance"):
                task["acceptance"] = self._fallback_acceptance(task, goal_spec)
                changes.append(f"{task.get('task_id')}: added observable acceptance")
            if not task.get("expected_artifacts") or task.get("expected_artifacts") in [
                ["implementation artifact"],
                ["planning artifact"],
            ]:
                task["expected_artifacts"] = self._fallback_artifacts(task, goal_spec)
                changes.append(f"{task.get('task_id')}: added concrete artifacts")
            allowed_tools = list(task.get("allowed_tools") or [])
            if task.get("task_kind", "implementation") in {"implementation", "ui"}:
                for tool in ["apply_patch", "run_command"]:
                    if tool not in allowed_tools:
                        allowed_tools.append(tool)
                        changes.append(f"{task.get('task_id')}: allowed {tool}")
            if task.get("verification_policy", {}).get("required"):
                for tool in ["run_tests", "run_command"]:
                    if tool not in allowed_tools:
                        allowed_tools.append(tool)
                        changes.append(f"{task.get('task_id')}: allowed {tool}")
            task["allowed_tools"] = allowed_tools
            task["updated_at"] = now_iso()
            notes = str(task.get("notes") or "")
            issue_summary = self.issue_summary(task_plan_eval)
            marker = f"Auto-revised by task plan quality gate: {issue_summary}."
            if marker not in notes:
                task["notes"] = f"{notes}\n{marker}".strip()
            task["completion_contract"] = completion_contract(task)
        return revised, list(dict.fromkeys(changes))

    def _fallback_acceptance(self, task: dict, goal_spec: dict) -> list[str]:
        for item in goal_spec.get("definition_of_done", []):
            if isinstance(item, str) and item.strip():
                return [item.strip()]
        artifacts = self._fallback_artifacts(task, goal_spec)
        return [f"{artifacts[0]} exists and can be reviewed"]

    def _fallback_artifacts(self, task: dict, goal_spec: dict) -> list[str]:
        for artifact in goal_spec.get("target_outputs", []):
            if isinstance(artifact, str) and "." in artifact and artifact.strip():
                return [artifact.strip()]
        title = str(task.get("title") or "artifact").lower()
        if "readme" in title or "doc" in title:
            return ["README.md"]
        if "test" in title:
            return ["tests/"]
        return ["src/"]

    def refresh(self, run_id: str, run_dir: Path, eval_path: Path) -> dict | None:
        goal_spec_path = run_dir / "goal_spec.json"
        task_plan_path = run_dir / "task_plan.json"
        if not goal_spec_path.exists() or not task_plan_path.exists():
            return None
        goal_spec = self.store.read(goal_spec_path, "goal_spec")
        task_plan = self.store.read(task_plan_path, "task_board")
        task_plan_eval = TaskPlanEvaluator().evaluate(task_plan, goal_spec, run_id=run_id)
        self.store.write(eval_path, task_plan_eval, "task_plan_eval")
        return task_plan_eval

    def issue_codes(self, task_plan_eval: dict) -> list[str]:
        return [
            str(issue.get("code"))
            for issue in task_plan_eval.get("issues", [])[:10]
            if isinstance(issue, dict)
        ]

    def issue_summary(self, task_plan_eval: dict) -> str:
        issues = [
            str(issue.get("code"))
            for issue in task_plan_eval.get("issues", [])[:5]
            if isinstance(issue, dict) and issue.get("code")
        ]
        if not issues:
            return "no issue details recorded"
        extra = len(task_plan_eval.get("issues", [])) - len(issues)
        suffix = f", +{extra} more" if extra > 0 else ""
        return ", ".join(issues) + suffix

    def _quality_decisions(self, run_id: str) -> list[dict]:
        run_dir = self.root / ".agent" / "runs" / run_id
        return [
            decision
            for decision in self._decisions(run_dir)
            if (decision.get("metadata") or {}).get("kind") == "task_plan_quality_gate"
        ]

    def _quality_bypassed(self, decisions: list[dict], task_plan_eval: dict) -> bool:
        for decision in decisions:
            if decision["status"] not in {"resolved", "defaulted"}:
                continue
            option = self._selected_decision_option(decision)
            metadata = decision.get("metadata") or {}
            if (
                option
                and option.get("action") == "record_constraint"
                and metadata.get("status") == task_plan_eval["status"]
                and metadata.get("overall_score") == task_plan_eval["overall_score"]
                and metadata.get("issue_codes") == self.issue_codes(task_plan_eval)
            ):
                return True
        return False

    def _active_revision_task(self, run_id: str, decisions: list[dict]) -> bool:
        revision_decision_ids = {
            decision["decision_id"]
            for decision in decisions
            if decision["status"] in {"resolved", "defaulted"}
            and (self._selected_decision_option(decision) or {}).get("action") == "require_replan"
        }
        if not revision_decision_ids:
            return False
        task_plan_path = self.root / ".agent" / "runs" / run_id / "task_plan.json"
        if not task_plan_path.exists():
            return False
        task_plan = self.store.read(task_plan_path, "task_board")
        active_statuses = {"ready", "backlog", "in_progress", "testing", "reviewing", "blocked"}
        for task in task_plan["tasks"]:
            if task["status"] not in active_statuses:
                continue
            notes = str(task.get("notes") or "")
            if any(decision_id in notes for decision_id in revision_decision_ids):
                return True
        return False

    def _selected_decision_option(self, decision: dict) -> dict | None:
        selected = decision.get("selected_option_id") or decision.get("default_option_id")
        for option in decision.get("options", []):
            if option.get("option_id") == selected:
                return option
        return None

    def _create_decision(self, run_id: str, task_plan_eval: dict, eval_path: Path) -> dict:
        options = [
            {
                "option_id": "revise_plan",
                "label": "Revise plan first",
                "tradeoff": "Spend a planning iteration before execution to avoid unverifiable work.",
                "action": "require_replan",
            },
            {
                "option_id": "proceed_once",
                "label": "Proceed once",
                "tradeoff": "Bypass this gate once, accepting higher risk of wasted execution.",
                "action": "record_constraint",
            },
        ]
        result = DecideCommand(
            self.root,
            run_id=run_id,
            question=(
                "Task plan quality failed before execution. "
                f"Score: {task_plan_eval['overall_score']:.2f}. "
                f"Issues: {self.issue_summary(task_plan_eval)}. Revise the plan first?"
            ),
            options_json=json.dumps(options, ensure_ascii=False),
            recommended_option_id="revise_plan",
            default_option_id="revise_plan",
            impact_json=json.dumps(
                {"scope": "medium", "budget": "medium", "risk": "high", "quality": "high"},
                ensure_ascii=False,
            ),
            metadata={
                "kind": "task_plan_quality_gate",
                "task_plan_eval": str(eval_path),
                "status": task_plan_eval["status"],
                "overall_score": task_plan_eval["overall_score"],
                "issue_count": len(task_plan_eval.get("issues", [])),
                "issue_codes": self.issue_codes(task_plan_eval),
            },
        ).run()
        return result.decisions[0]

    def _pause_run(self, run_id: str, summary: str) -> None:
        run_store = RunStore(self.root / ".agent", self.validator)
        run = run_store.load_run(run_id)
        run["status"] = "paused"
        run["current_phase"] = "DECISION"
        run["summary"] = summary
        run_store.update_run(run)

    def _decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return self.jsonl.read_all(path, "decision_point")
