from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.commands.correctness_eval_command import CorrectnessEvalCommand
from asteria_runtime.core.agent_harness import (
    latest_observation_next_action_plan,
    load_raw_tool_observations,
    observation_next_action_plan,
    tool_observation_action_options,
)
from asteria_runtime.core.active_next_step import capability_feedback_active_next_step
from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.fast_path_policy import classify_fast_path
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.prompt_envelope import persist_prompt_envelope
from asteria_runtime.core.real_provider_matrix import (
    latest_real_provider_matrix,
    real_provider_matrix_text_lines,
)
from asteria_runtime.core.execution_profile import (
    execution_profile_from_run_config,
    session_agent_recommended_command,
)
from asteria_runtime.core.run_config import effective_policy_for_run, load_run_config
from asteria_runtime.core.runtime_evidence import RuntimeEvidenceReader
from asteria_runtime.core.context_slimming import slim_review_context
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.models.route_resolver import route_health_for_tiers
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.tools.defaults import create_default_tool_registry
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ReviewResult:
    run_id: str
    status: str
    score: float | None
    eval_report_path: Path
    review_report_path: Path
    cost_report_path: Path
    follow_up_count: int = 0
    decision_count: int = 0
    blockers: list[str] | None = None
    next_actions: list[str] | None = None
    recommended_next_command: str | None = None
    failure_classification: dict | None = None

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "status": self.status,
            "score": self.score,
            "eval_report_path": str(self.eval_report_path),
            "review_report_path": str(self.review_report_path),
            "cost_report_path": str(self.cost_report_path),
            "follow_up_count": self.follow_up_count,
            "decision_count": self.decision_count,
            "blockers": self.blockers or [],
            "primary_blocker": self.primary_blocker,
            "next_actions": self.next_actions or [],
            "recommended_next_command": self.recommended_next_command,
            "failure_classification": self.failure_classification or {},
        }

    @property
    def primary_blocker(self) -> str | None:
        blockers = self.blockers or []
        return blockers[0] if blockers else None

    def to_text(self) -> str:
        lines = [
            f"Reviewed run: {self.run_id}",
            f"Status: {self.status}",
            f"Score: {self.score:.2f}" if self.score is not None else "Score: unverified",
            f"Eval report: {self.eval_report_path}",
            f"Review report: {self.review_report_path}",
            f"Cost report: {self.cost_report_path}",
            f"Follow-up tasks: {self.follow_up_count}",
            f"Decision points: {self.decision_count}",
        ]
        if self.failure_classification:
            lines.append(
                "Failure classification: "
                f"{self.failure_classification.get('category')} -> "
                f"{self.failure_classification.get('recommended_command')}"
            )
        if self.primary_blocker:
            lines.append(f"Primary blocker: {self.primary_blocker}")
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {item}" for item in self.next_actions)
        if self.recommended_next_command:
            lines.append(f"Recommended next command: asteria {self.recommended_next_command}")
        return "\n".join(lines)


class ReviewCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        model_client: ModelClient | None = None,
        *,
        rerun: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.model_client = model_client
        # Opt-in: when set, the correctness signal is the INDEPENDENT re-run (recorded verification
        # commands re-executed against the current workspace) rather than trusting recorded exit
        # codes. Default off → byte-identical read-only review.
        self.rerun = rerun
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.runtime_evidence = RuntimeEvidenceReader(self.validator)

    def run(self) -> ReviewResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `asteria plan` first.")
        run_dir = run_store.run_dir(run_id)
        run = run_store.load_run(run_id)
        policy = effective_policy_for_run(
            policy=load_policy_config(agent_dir, self.validator),
            run_dir=run_dir,
            validator=self.validator,
        )
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(
            policy,
            self._read_cost(cost_report_path, run_id),
            run_id=run_id,
        )
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)

        run["status"] = "running"
        run["current_phase"] = "REVIEW"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "ReviewCommand", "DONE -> REVIEW")

        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
        progress.record(
            run_id=run_id,
            channel="progress",
            phase="review",
            status="running",
            title="开始评审",
            summary="正在汇总执行结果、证据和产物，准备进行质量评审。",
            display_level="main",
        )
        prompt_envelope = persist_prompt_envelope(
            root=self.root,
            run_dir=run_dir,
            run_id=run_id,
            mode="review",
            policy=policy,
            validator=self.validator,
            tool_names=create_default_tool_registry().names(),
            event_logger=event_logger,
            progress_logger=progress,
            phase="review",
            actor="ReviewCommand",
        )

        review_context = self._review_context(agent_dir, run_dir, run_id)
        review_context["prompt_envelope"] = prompt_envelope.context_ref()
        review_context["tool_observations"] = load_raw_tool_observations(run_dir)
        review_context["latest_observation_plan"] = (
            latest_observation_next_action_plan(run_dir, self.validator) or {}
        )
        review_context["tool_observation_actions"] = tool_observation_action_options(
            review_context["tool_observations"]
        )
        # Real correctness signal (graded verification pass rate) so the review overall score is
        # the actual exit-code evidence, not a 0.9/0.6/0.2 status constant. None when the run had
        # no executable verification — callers then keep the deterministic status-derived value.
        # With --rerun the signal is INDEPENDENT: recorded verification commands are re-executed
        # against the current workspace, so a recorded pass that is now broken/stale is caught.
        review_context["correctness_signal"] = CorrectnessEvalCommand(
            self.root, run_id, rerun=self.rerun
        ).score_signal(run_dir)
        progress.record(
            run_id=run_id,
            channel="progress",
            phase="review",
            status="running",
            title="评审分析中",
            summary="正在用分层评审策略分析执行证据，判断目标完成情况。",
            display_level="main",
        )
        eval_report = self._deterministic_tiered_eval_report(review_context, run_id)
        if eval_report is not None:
            event_logger.record(
                run_id,
                "tiered_review_deterministic_pass",
                "ReviewCommand",
                "Deterministic-first review accepted the fast-path run without a model call.",
                eval_report["trajectory_eval"].get("review_tier", {}),
            )
            progress.record(
                run_id=run_id,
                channel="validation",
                event_type="validation_result",
                phase="review",
                status="completed",
                title="确定性评审通过",
                summary="执行证据已满足快路径评审条件，无需调用强模型复审。",
                data={"validation": eval_report["trajectory_eval"].get("review_tier", {})},
                display_level="main",
            )
        else:
            reviewer = ReviewAgent(self._model_client(run_dir, budget), self.validator)
            model_review_context = (
                slim_review_context(review_context)
                if self.model_client is None
                else review_context
            )
            try:
                eval_report = reviewer.evaluate(model_review_context, run_id)
            except Exception:
                self.store.write(
                    cost_report_path,
                    self._merge_cost_reports(
                        budget.cost_report(),
                        self._read_cost(cost_report_path, run_id),
                    ),
                    "cost_report",
                )
                raise
        eval_report["trajectory_eval"] = dict(eval_report.get("trajectory_eval") or {})
        eval_report["trajectory_eval"]["route_health"] = review_context["route_health"]
        eval_report["trajectory_eval"]["model_selection"] = review_context["model_selection"]
        failure_classification = self._failure_classification(eval_report)
        eval_report["failure_classification"] = failure_classification
        eval_report["trajectory_eval"]["failure_classification"] = failure_classification
        eval_report_path = run_dir / "eval_report.json"
        self.store.write(eval_report_path, eval_report, "eval_report")
        follow_up_count = 0
        decision_count = 0
        review_report_path = run_dir / "review_report.md"
        review_report_path.write_text(
            self._markdown_report(
                eval_report,
                review_context.get("collaboration_summary") or {},
                review_context.get("tool_observations") or [],
                review_context.get("latest_observation_plan") or {},
                review_context.get("route_health") or {},
                review_context.get("model_selection") or {},
                review_context.get("latest_real_provider_matrix") or {},
            ),
            encoding="utf-8",
        )
        status = eval_report["overall"]["status"]
        raw_score = eval_report["overall"]["score"]
        # ADR-0016 §3: score is None for an unverified task (no executable verification, no model
        # score) — surface it honestly as "未验证" instead of a fabricated number.
        score = float(raw_score) if raw_score is not None else None
        score_text = f"{score:.2f}" if score is not None else "未验证"
        reason = str(eval_report["overall"].get("reason", ""))
        progress.validation_event(
            run_id=run_id,
            title="评审结论已生成",
            summary=f"评审状态为 {status}，评分 {score_text}。{reason}",
            validation={
                "status": status,
                "score": score,
                "reason": reason,
                "follow_up_count": follow_up_count,
                "decision_count": decision_count,
                "recommended_next_command": self._result_recommended_next_command(
                    status,
                    decision_count,
                    failure_classification,
                ),
            },
            phase="review",
            status="completed" if status == "pass" else "blocked",
            evidence_refs=[str(eval_report_path)],
        )
        progress.artifact_event(
            run_id=run_id,
            title="评审报告已写入",
            summary="评审报告和评估 JSON 已保存，可供用户结果页和 Inspector 读取。",
            artifact_refs=[str(eval_report_path), str(review_report_path)],
            phase="review",
        )
        event_logger.record(
            run_id,
            "artifact_created",
            "ReviewAgent",
            f"EvalReport created with status {eval_report['overall']['status']}",
            {"path": "eval_report.json", "score": eval_report["overall"]["score"]},
        )

        self.store.write(
            cost_report_path,
            self._merge_cost_reports(
                budget.cost_report(),
                self._read_cost(cost_report_path, run_id),
            ),
            "cost_report",
        )
        if status == "pass":
            run["status"] = "completed"
            run["current_phase"] = "REVIEWED"
            run["ended_at"] = now_iso()
        elif decision_count:
            run["status"] = "paused"
            run["current_phase"] = "DECISION"
        elif status == "partial":
            run["status"] = "running"
            run["current_phase"] = "REVIEWED"
        else:
            run["status"] = "blocked"
            run["current_phase"] = "REVIEWED"
        run["summary"] = eval_report["overall"]["reason"]
        run_store.update_run(run)

        blockers = self._result_blockers(eval_report, follow_up_count, decision_count)
        next_actions = self._result_next_actions(status, follow_up_count, decision_count)
        self._write_active_goal_memory(
            run_dir=run_dir,
            run_status=run,
            review_status=status,
            completion="implemented_needs_accept" if status == "pass" else "blocked",
            blockers=blockers,
            next_actions=next_actions,
        )

        progress.conclusion(
            run_id=run_id,
            phase="review",
            title="评审完成",
            summary=f"评分 {score_text}（{status}）。{reason}",
            artifact_refs=[str(eval_report_path), str(review_report_path)],
        )

        return ReviewResult(
            run_id=run_id,
            status=status,
            score=score,
            eval_report_path=eval_report_path,
            review_report_path=review_report_path,
            cost_report_path=cost_report_path,
            follow_up_count=follow_up_count,
            decision_count=decision_count,
            blockers=blockers,
            next_actions=next_actions,
            recommended_next_command=self._result_recommended_next_command(
                status,
                decision_count,
                failure_classification,
            ),
            failure_classification=failure_classification,
        )

    def _deterministic_tiered_eval_report(self, review_context: dict, run_id: str) -> dict | None:
        if self.model_client is not None:
            return None
        goal_spec = review_context.get("goal_spec")
        task_plan = review_context.get("task_plan")
        checks = review_context.get("deterministic_checks")
        cost_report = review_context.get("cost_report")
        if not isinstance(goal_spec, dict) or not isinstance(task_plan, dict):
            return None
        if not isinstance(checks, dict) or not isinstance(cost_report, dict):
            return None
        fast_path = classify_fast_path(
            str(goal_spec.get("original_goal") or goal_spec.get("normalized_goal") or ""),
            target_files=self._review_target_files(goal_spec, task_plan),
        )
        if fast_path.risk_tier == "high":
            return None
        blockers = self._tiered_review_blockers(
            checks,
            review_tier=fast_path.review_tier,
            fast_path_task_kind=fast_path.task_kind,
        )
        if blockers:
            return None
        report = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "goal_eval": {"requirement_coverage": 1.0},
            "artifact_eval": {"artifacts_present": True, "logs_present": True},
            "outcome_eval": {"verification_pass_rate": 1.0, "run_success": True},
            "trajectory_eval": {
                "blocked_task_count": 0,
                "review_tier": {
                    "mode": "deterministic_first",
                    "accepted_without_model": True,
                    "fast_path": fast_path.to_dict(),
                    "reason": "Fast-path run completed with deterministic verification evidence.",
                },
            },
            "cost_eval": {
                "status": cost_report.get("status", "within_budget"),
                "model_calls": cost_report.get("model_calls", 0),
                "tool_calls": cost_report.get("tool_calls", 0),
            },
            "overall": self._fast_path_overall(review_context.get("correctness_signal")),
        }
        self.validator.validate("eval_report", report)
        return report

    def _fast_path_overall(self, correctness: dict | None) -> dict:
        # ADR-0016 §3: the fast-path status ("pass") is a real deterministic invariant (all active
        # tasks done, no blockers), but the SCORE must be evidence, never a fabricated constant.
        # Use the real verification pass rate when the run ran executable verification; when it did
        # NOT (e.g. a doc/creative fast-path with no run_tests/run_command), the score is None
        # ("unverified") — the same de-fabrication applied to ReviewAgent._overall, not a fake 0.9.
        base_reason = (
            "Deterministic-first review passed: all active tasks are done, "
            "verification passed, and no unresolved runtime blockers were found."
        )
        if isinstance(correctness, dict):
            return {
                "status": "pass",
                "score": float(correctness["score"]),
                "reason": f"{base_reason} Score is the real verification pass rate "
                f"({float(correctness['score']):.2f}).",
            }
        return {
            "status": "pass",
            "score": None,
            "reason": (
                f"{base_reason} Unverified: no executable verification (run_tests/run_command) ran, "
                "so the score is not a real pass rate; needs an explicit human accept."
            ),
        }

    def _review_target_files(self, goal_spec: dict, task_plan: dict) -> list[str]:
        files: list[str] = []
        for item in goal_spec.get("target_outputs") or []:
            if isinstance(item, str) and item:
                files.append(item)
        for task in task_plan.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            for item in task.get("expected_artifacts") or []:
                if isinstance(item, str) and item:
                    files.append(item)
        return list(dict.fromkeys(files))

    def _tiered_review_blockers(
        self,
        checks: dict,
        *,
        review_tier: str = "deterministic",
        fast_path_task_kind: str | None = None,
    ) -> list[str]:
        blockers: list[str] = []
        if float(checks.get("task_completion_rate") or 0) < 1.0:
            blockers.append("task_completion_incomplete")
        if int(checks.get("blocked_task_count") or 0) > 0:
            blockers.append("blocked_tasks_present")
        requires_command_verification = fast_path_task_kind in {
            "bug_fix",
            "single_file_bugfix",
        }
        if review_tier in {"deterministic", "deterministic_then_medium"} and not requires_command_verification:
            if int(checks.get("verification_call_count") or 0) <= 0:
                blockers.append("missing_verification_call")
            if float(checks.get("verification_pass_rate") or 0) < 1.0:
                blockers.append("verification_not_fully_passing")
        else:
            if int(checks.get("command_verification_call_count") or 0) <= 0:
                blockers.append("missing_command_verification_call")
            if float(checks.get("command_verification_pass_rate") or 0) < 1.0:
                blockers.append("command_verification_not_fully_passing")
        if int(checks.get("unrecovered_failed_worker_result_count") or 0) > 0:
            blockers.append("failed_worker_results_present")
        if int(checks.get("merge_gate_block_count") or 0) > 0:
            blockers.append("merge_gate_blocks_present")
        if int(checks.get("pending_runtime_request_count") or 0) > 0:
            blockers.append("pending_runtime_requests_present")
        if str(checks.get("cost_status") or "within_budget") not in {"within_budget", "healthy"}:
            blockers.append("cost_not_within_budget")
        return blockers

    def _result_blockers(
        self,
        eval_report: dict,
        follow_up_count: int,
        decision_count: int,
    ) -> list[str]:
        overall = eval_report.get("overall") or {}
        status = str(overall.get("status") or "unknown")
        if status == "pass":
            return []
        blockers = [f"Review verdict is {status}: {overall.get('reason') or 'no reason recorded'}"]
        if decision_count:
            blockers.append(
                f"{decision_count} decision point(s) must be resolved before acceptance."
            )
        if follow_up_count:
            blockers.append(f"{follow_up_count} follow-up task(s) were created by review.")
        return blockers

    def _result_next_actions(
        self,
        status: str,
        follow_up_count: int,
        decision_count: int,
    ) -> list[str]:
        if status == "pass":
            return ["Run `asteria accept` to finalize accepted work."]
        if decision_count:
            return [
                "Run `asteria decide --list`, resolve pending decisions, then rerun `asteria review`."
            ]
        actions = ["Run the recommended repair command, then rerun `asteria review`."]
        if follow_up_count:
            actions.append("Inspect newly created follow-up tasks before continuing execution.")
        return actions

    def _result_recommended_next_command(
        self,
        status: str,
        decision_count: int,
        failure_classification: dict | None = None,
    ) -> str:
        if status == "pass":
            return "accept"
        if decision_count:
            return "decide --list"
        classified = (failure_classification or {}).get("recommended_command")
        if classified:
            return str(classified)
        return "debug"

    def _failure_classification(self, eval_report: dict) -> dict:
        overall = eval_report.get("overall") or {}
        status = str(overall.get("status") or "unknown")
        overall_reason = str(overall.get("reason") or "").lower()
        if status == "pass":
            return {
                "category": "none",
                "recommended_command": "accept",
                "reason": "Review passed.",
            }
        goal_eval = eval_report.get("goal_eval") or {}
        artifact_eval = eval_report.get("artifact_eval") or {}
        outcome_eval = eval_report.get("outcome_eval") or {}
        trajectory_eval = eval_report.get("trajectory_eval") or {}
        coverage = float(goal_eval.get("requirement_coverage", 1.0) or 0.0)
        artifacts_present = artifact_eval.get("artifacts_present", True)
        blocked_tasks = int(trajectory_eval.get("blocked_task_count", 0) or 0)
        verification_rate = float(outcome_eval.get("verification_pass_rate", 1.0) or 0.0)
        if coverage < 0.8 or artifacts_present is False:
            classification = {
                "category": "plan_gap",
                "recommended_command": "resume",
                "reason": "Requirement coverage or artifact fit is insufficient; continue the session with this review feedback.",
            }
            return self._soften_failure_classification(eval_report, classification)
        if blocked_tasks > 0:
            return {
                "category": "execution_blocked",
                "recommended_command": "resume",
                "reason": "Execution has blocked tasks; continue the session from the concrete failure evidence.",
            }
        if verification_rate < 1.0 or "verification" in overall_reason:
            return {
                "category": "verification_failed",
                "recommended_command": "resume",
                "reason": "Verification did not pass; continue the session with the review findings.",
            }
        return {
            "category": "review_failed",
            "recommended_command": "resume",
            "reason": f"Review status is {status}; continue the session with the recorded feedback.",
        }

    def _soften_failure_classification(self, eval_report: dict, classification: dict) -> dict:
        run_id = str(eval_report.get("run_id") or "").strip()
        if not run_id:
            return classification
        run_dir = self.root / ".asteria" / "runs" / run_id
        profile = execution_profile_from_run_config(load_run_config(run_dir, self.validator))
        command = str(classification.get("recommended_command") or "")
        softened = session_agent_recommended_command(command, is_session_agent=profile.is_session_agent)
        if softened == command:
            return classification
        updated = dict(classification)
        updated["recommended_command"] = softened
        if softened == "resume":
            updated["reason"] = (
                f"{classification.get('reason', '')} "
                "Session-agent profile retries in-place via resume."
            ).strip()
        return updated

    def _follow_ups(self, eval_report: dict) -> list[dict]:
        follow_ups = eval_report.get("outcome_eval", {}).get("follow_up_tasks", [])
        if not follow_ups:
            follow_ups = eval_report.get("trajectory_eval", {}).get("follow_up_tasks", [])
        if not isinstance(follow_ups, list):
            return []
        return [item for item in follow_ups if isinstance(item, dict)]

    def _merge_cost_reports(self, review_cost: dict, latest_cost: dict) -> dict:
        merged = dict(review_cost)
        merged["user_decisions"] = max(
            int(review_cost.get("user_decisions", 0)),
            int(latest_cost.get("user_decisions", 0)),
        )
        warnings = list(review_cost.get("warnings", []))
        for warning in latest_cost.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
        merged["warnings"] = warnings
        merged["status"] = "near_limit" if warnings else review_cost.get("status", "within_budget")
        return merged

    def _review_context(self, agent_dir: Path, run_dir: Path, run_id: str) -> dict:
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        task_plan = self.store.read(run_dir / "task_plan.json", "task_board")
        cost_report = self._read_cost(run_dir / "cost_report.json", run_id)
        tool_calls = self._read_jsonl(run_dir / "tool_calls.jsonl", "tool_call")
        tool_observations = self._read_jsonl(
            run_dir / "tool_observations.jsonl",
            "tool_observation",
        )
        model_calls = self._read_jsonl(run_dir / "model_calls.jsonl", "model_call")
        model_profiles = self._read_jsonl(run_dir / "model_profiles.jsonl", "model_profile")
        route_health = self._route_health(model_profiles)
        events = self._read_jsonl(run_dir / "events.jsonl", "event")
        runtime_os_evidence = self.runtime_evidence.run_evidence(run_dir)
        execution_evidence = runtime_os_evidence["task_execution_evidence"]
        model_selection = self._latest_model_selection(execution_evidence)
        return {
            "run_id": run_id,
            "project": self.store.read(agent_dir / "project.json", "project_config"),
            "goal_spec": goal_spec,
            "task_plan": task_plan,
            "cost_report": cost_report,
            "collaboration_summary": self._collaboration_summary(run_dir),
            "route_health": route_health,
            "model_selection": model_selection,
            "latest_real_provider_matrix": latest_real_provider_matrix(agent_dir),
            "trajectory": {
                "runtime_os_evidence": runtime_os_evidence,
                "events": events[-50:],
                "tool_calls": tool_calls[-50:],
                "tool_observations": tool_observations[-50:],
                "tool_observation_actions": tool_observation_action_options(tool_observations),
                "model_calls": model_calls[-20:],
                "model_profiles": model_profiles[-20:],
                "route_health": route_health,
                "model_selection": model_selection,
                "task_execution_evidence": execution_evidence[-20:],
                "worker_results": runtime_os_evidence["worker_results"][-20:],
                "merge_gate_evidence": runtime_os_evidence["merge_gate_evidence"][-20:],
                "runtime_requests": runtime_os_evidence["runtime_requests"][-20:],
            },
            "deterministic_checks": self._deterministic_checks(
                task_plan,
                tool_calls,
                cost_report,
                runtime_os_evidence,
            ),
        }

    def _collaboration_summary(self, run_dir: Path) -> dict:
        path = run_dir / "agent_run_graph.json"
        if not path.exists():
            return {}
        try:
            graph = self.store.read(path, "agent_run_graph")
            return graph.get("collaboration_summary") or {}
        except Exception:  # noqa: BLE001
            return {}

    def _latest_model_selection(self, execution_evidence: list[dict]) -> dict:
        for evidence in reversed(execution_evidence):
            selection = (evidence.get("action") or {}).get("model_selection")
            if isinstance(selection, dict) and selection:
                return selection
        return {}

    def _route_health(self, model_profiles: list[dict]) -> dict:
        if not model_profiles:
            return {
                "status": "unknown",
                "summary": "No model profiles were mounted for review.",
                "routes": [],
                "blockers": [],
            }
        latest_by_tier: dict[str, dict] = {}
        for profile in model_profiles:
            tier = str(profile.get("model_tier") or "unknown")
            latest_by_tier[tier] = profile
        return route_health_for_tiers(tuple(latest_by_tier))

    def _deterministic_checks(
        self,
        task_plan: dict,
        tool_calls: list[dict],
        cost_report: dict,
        runtime_os_evidence: dict | None = None,
    ) -> dict:
        runtime_os_evidence = runtime_os_evidence or {}
        execution_evidence = runtime_os_evidence.get("task_execution_evidence") or []
        worker_results = runtime_os_evidence.get("worker_results") or []
        merge_gate_evidence = runtime_os_evidence.get("merge_gate_evidence") or []
        runtime_requests = runtime_os_evidence.get("runtime_requests") or []
        runtime_summary = runtime_os_evidence.get("summary") or {}
        tasks = task_plan.get("tasks", [])
        active_tasks = [task for task in tasks if task["status"] != "discarded"]
        discarded_task_ids = {
            str(task.get("task_id") or "") for task in tasks if task.get("status") == "discarded"
        }
        done = [task for task in active_tasks if task["status"] == "done"]
        blocked = [task for task in active_tasks if task["status"] == "blocked"]
        command_verification_calls = [
            call for call in tool_calls if call["tool_name"] in {"run_tests", "run_command"}
        ]
        artifact_readback_calls = [
            call for call in tool_calls if call["tool_name"] in {"read_file"}
        ]
        verification_calls = [*command_verification_calls, *artifact_readback_calls]
        passed_verification = [call for call in verification_calls if call["status"] == "success"]
        passed_command_verification = [
            call for call in command_verification_calls if call["status"] == "success"
        ]
        return {
            "task_completion_rate": len(done) / len(active_tasks) if active_tasks else 0,
            "blocked_task_count": len(blocked),
            "discarded_task_count": len(tasks) - len(active_tasks),
            "task_execution_evidence_count": len(execution_evidence),
            "latest_execution_status": (
                execution_evidence[-1].get("status") if execution_evidence else None
            ),
            "worker_result_count": len(worker_results),
            "failed_worker_result_count": len(
                [item for item in worker_results if item.get("status") != "succeeded"]
            ),
            "unrecovered_failed_worker_result_count": self._unrecovered_failed_worker_count(
                worker_results,
                execution_evidence,
                discarded_task_ids=discarded_task_ids,
                all_active_tasks_done=len(done) == len(active_tasks) and bool(active_tasks),
            ),
            "merge_gate_block_count": len(
                [
                    item
                    for item in merge_gate_evidence
                    if isinstance(item.get("merge_gate"), dict)
                    and item["merge_gate"].get("ok") is False
                ]
            ),
            "runtime_request_count": len(runtime_requests),
            "pending_runtime_request_count": len(
                [
                    item
                    for item in runtime_requests
                    if item.get("status") in {"recorded", "decision_created"}
                ]
            ),
            "runtime_os_summary": runtime_summary,
            "verification_call_count": len(verification_calls),
            "verification_pass_rate": (
                len(passed_verification) / len(verification_calls) if verification_calls else 0
            ),
            "command_verification_call_count": len(command_verification_calls),
            "command_verification_pass_rate": (
                len(passed_command_verification) / len(command_verification_calls)
                if command_verification_calls
                else 0
            ),
            "artifact_readback_call_count": len(artifact_readback_calls),
            "cost_status": cost_report.get("status", "within_budget"),
        }

    def _unrecovered_failed_worker_count(
        self,
        worker_results: list[dict],
        execution_evidence: list[dict],
        *,
        discarded_task_ids: set[str] | None = None,
        all_active_tasks_done: bool = False,
    ) -> int:
        recovered_tasks = self._recovered_task_ids(execution_evidence)
        discarded_task_ids = discarded_task_ids or set()
        return len(
            [
                item
                for item in worker_results
                if item.get("status") != "succeeded"
                and not self._worker_failure_is_recovered(
                    str(item.get("task_id") or ""),
                    recovered_tasks=recovered_tasks,
                    discarded_task_ids=discarded_task_ids,
                    all_active_tasks_done=all_active_tasks_done,
                )
            ]
        )

    def _worker_failure_is_recovered(
        self,
        task_id: str,
        *,
        recovered_tasks: set[str],
        discarded_task_ids: set[str],
        all_active_tasks_done: bool,
    ) -> bool:
        if task_id in recovered_tasks:
            return True
        return all_active_tasks_done and task_id in discarded_task_ids

    def _recovered_task_ids(self, execution_evidence: list[dict]) -> set[str]:
        latest_by_task: dict[str, dict] = {}
        for item in execution_evidence:
            task_id = str(item.get("task_id") or "")
            if task_id:
                latest_by_task[task_id] = item
        return {
            task_id
            for task_id, item in latest_by_task.items()
            if self._execution_evidence_is_recovered(item)
        }

    def _execution_evidence_is_recovered(self, evidence: dict) -> bool:
        if evidence.get("status") != "done":
            return False
        contract = evidence.get("contract_check")
        if isinstance(contract, dict) and contract.get("ok") is False:
            return False
        verification_results = evidence.get("verification_results")
        if isinstance(verification_results, list) and any(
            isinstance(item, dict) and item.get("ok") is False for item in verification_results
        ):
            return False
        return True

    def _markdown_report(
        self,
        eval_report: dict,
        collaboration_summary: dict | None = None,
        tool_observations: list[dict] | None = None,
        latest_observation_plan: dict | None = None,
        route_health: dict | None = None,
        model_selection: dict | None = None,
        latest_real_provider_matrix: dict | None = None,
    ) -> str:
        overall = eval_report["overall"]
        action_plan = observation_next_action_plan(tool_observations or [])
        latest_plan = latest_observation_plan or {}
        effective_plan = latest_plan or action_plan
        route_health = route_health or {}
        model_selection = model_selection or {}
        latest_real_provider_matrix = latest_real_provider_matrix or {}
        blockers = self._human_blockers(eval_report, action_plan, latest_plan, route_health)
        evidence = self._human_evidence(
            eval_report,
            collaboration_summary or {},
            action_plan,
            latest_plan,
            route_health,
            model_selection,
        )
        next_actions = self._human_next_actions(eval_report, effective_plan, blockers)
        trajectory_eval_for_report = self._product_trajectory_eval(eval_report["trajectory_eval"])
        lines = [
            "# Review Report",
            "",
            "## Conclusion",
            "",
            f"- Verdict: {overall['status']}",
            f"- Score: {overall['score']}",
            f"- Reason: {overall['reason']}",
            f"- Recommended next action: {effective_plan.get('recommended_route') or action_plan['recommended_action']}",
            "",
            "## Blocking Reasons",
            "",
            *([f"- {item}" for item in blockers] if blockers else ["- None."]),
            "",
            "## Evidence Chain",
            "",
            *(
                [f"- {item}" for item in evidence]
                if evidence
                else ["- Eval report and review report were generated."]
            ),
            "",
            "## Latest Agent Next Action",
            "",
            f"- Route: {effective_plan.get('recommended_route') or action_plan.get('recommended_action', 'continue')}",
            f"- Why this route was chosen: {effective_plan.get('reason') or self._latest_plan_reason(action_plan)}",
            f"- Evidence: {self._latest_plan_evidence(effective_plan)}",
            "",
            "## Failure Classification",
            "",
            *self._failure_classification_lines(eval_report),
            "",
            "## Model Route Health",
            "",
            f"- Status: {route_health.get('status', 'unknown')}",
            f"- Summary: {route_health.get('summary', 'No route health recorded.')}",
            *[
                "- "
                f"{route.get('tier', 'unknown')}: "
                f"{route.get('provider', route.get('recorded_provider', 'unknown'))}/"
                f"{route.get('model_name', route.get('recorded_model_name', 'unknown'))} "
                f"configured={route.get('configured', False)}"
                for route in list(route_health.get("routes") or [])[:5]
            ],
            "",
            "## Model Selection",
            "",
            *self._model_selection_report_lines(model_selection),
            "## Latest Real Provider Matrix",
            "",
            *(
                [
                    f"- {line.strip()}"
                    for line in real_provider_matrix_text_lines(latest_real_provider_matrix)
                ]
                if latest_real_provider_matrix
                else ["- No real-provider P0 matrix evidence recorded."]
            ),
            "",
            "## Next Actions",
            "",
            *[f"- {item}" for item in next_actions],
            "",
            "## Goal Eval",
            "",
            f"```json\n{self._json(eval_report['goal_eval'])}\n```",
            "",
            "## Artifact Eval",
            "",
            f"```json\n{self._json(eval_report['artifact_eval'])}\n```",
            "",
            "## Outcome Eval",
            "",
            f"```json\n{self._json(eval_report['outcome_eval'])}\n```",
            "",
            "## Trajectory Eval",
            "",
            f"```json\n{self._json(trajectory_eval_for_report)}\n```",
            "",
            "## Cost Eval",
            "",
            f"```json\n{self._json(eval_report['cost_eval'])}\n```",
            "",
        ]
        collab = collaboration_summary or eval_report.get("collaboration_summary") or {}
        if collab:
            lines.extend(
                [
                    "## Multi-Agent Collaboration",
                    "",
                    f"- Workers: total={collab.get('total_workers', 0)}"
                    f" succeeded={collab.get('successful_workers', 0)}"
                    f" failed={collab.get('failed_workers', 0)}"
                    f" blocked={collab.get('blocked_workers', 0)}",
                    f"- Model calls: {collab.get('total_model_calls', 0)}"
                    f"  Tool calls: {collab.get('total_tool_calls', 0)}",
                ]
            )
            failure_refs = collab.get("failure_evidence_refs") or []
            if failure_refs:
                lines.append(f"- Failure evidence: {', '.join(failure_refs[:5])}")
            next_actions = collab.get("next_actions") or []
            for action in next_actions[:3]:
                lines.append(f"- Next: {action}")
            lines.append("")
        return "\n".join(lines)

    def _human_blockers(
        self,
        eval_report: dict,
        action_plan: dict,
        latest_plan: dict | None = None,
        route_health: dict | None = None,
        model_selection: dict | None = None,
    ) -> list[str]:
        blockers: list[str] = []
        overall = eval_report.get("overall") or {}
        if overall.get("status") != "pass":
            blockers.append(f"Review verdict is {overall.get('status')}: {overall.get('reason')}")
        source_plan = latest_plan or action_plan
        blockers.extend(str(item) for item in (route_health or {}).get("blockers") or [])
        blockers.extend(str(item) for item in source_plan.get("blockers") or [])
        follow_ups = self._follow_ups(eval_report)
        if follow_ups:
            blockers.append(f"{len(follow_ups)} follow-up item(s) remain from review.")
        return blockers[:10]

    def _human_evidence(
        self,
        eval_report: dict,
        collaboration_summary: dict,
        action_plan: dict,
        latest_plan: dict | None = None,
        route_health: dict | None = None,
        model_selection: dict | None = None,
    ) -> list[str]:
        source_plan = latest_plan or action_plan
        evidence = [
            f"overall={eval_report['overall'].get('status')} score={eval_report['overall'].get('score')}",
        ]
        if source_plan.get("failed_observation_count"):
            evidence.append(
                f"failed tool observations={source_plan.get('failed_observation_count')} "
                f"recommended={source_plan.get('recommended_route') or source_plan.get('recommended_action')}"
            )
        if source_plan.get("observation_plan_id"):
            evidence.append(f"observation plan={source_plan.get('observation_plan_id')}")
        for ref in source_plan.get("evidence_refs") or []:
            evidence.append(f"tool evidence: {ref}")
        if collaboration_summary:
            evidence.append(
                "worker evidence: "
                f"{collaboration_summary.get('successful_workers', 0)}/"
                f"{collaboration_summary.get('total_workers', 0)} workers succeeded"
            )
        if route_health:
            evidence.append(f"model routes={route_health.get('status', 'unknown')}")
            for route in list(route_health.get("routes") or [])[:3]:
                evidence.append(
                    "model route: "
                    f"{route.get('tier', 'unknown')} "
                    f"{route.get('provider', route.get('recorded_provider', 'unknown'))}/"
                    f"{route.get('model_name', route.get('recorded_model_name', 'unknown'))} "
                    f"configured={route.get('configured', False)}"
                )
        if model_selection:
            evidence.append(
                "model selection: "
                f"{model_selection.get('selected_tier', 'unknown')} "
                f"reason={model_selection.get('reason', 'unknown')}"
            )
            pressure = model_selection.get("tier_pressure") or {}
            if pressure:
                evidence.append(
                    "model pressure: "
                    f"{pressure.get('default_tier', 'unknown')} -> "
                    f"{pressure.get('selected_tier', 'unknown')} "
                    f"direction={pressure.get('direction', 'unknown')}"
                )
            feedback = model_selection.get("capability_feedback") or {}
            if feedback:
                evidence.append(
                    "capability feedback: "
                    f"{feedback.get('status', 'unknown')} "
                    f"decision={feedback.get('decision', 'unknown')}"
                )
        return evidence[:12]

    def _model_selection_report_lines(self, model_selection: dict) -> list[str]:
        if not model_selection:
            return ["- No model selection recorded in latest execution evidence."]
        lines = [
            f"- Purpose: {model_selection.get('purpose', 'unknown')}",
            f"- Selected tier: {model_selection.get('selected_tier', 'unknown')}",
            f"- Reason: {model_selection.get('reason', 'No reason recorded.')}",
        ]
        pressure = model_selection.get("tier_pressure") or {}
        if pressure:
            lines.append(
                "- Tier pressure: "
                f"{pressure.get('default_tier', 'unknown')} -> "
                f"{pressure.get('selected_tier', 'unknown')} "
                f"direction={pressure.get('direction', 'unknown')} "
                f"delta={pressure.get('delta', 0)}"
            )
        feedback = model_selection.get("capability_feedback") or {}
        if feedback:
            lines.append(
                "- Capability feedback: "
                f"{feedback.get('status', 'unknown')} "
                f"decision={feedback.get('decision', 'unknown')} "
                f"blocking={feedback.get('blocking_count', 0)} "
                f"review={feedback.get('review_count', 0)}"
            )
            lines.append(f"- Active next step: {capability_feedback_active_next_step(feedback)}")
        return lines

    def _product_trajectory_eval(self, trajectory_eval: dict) -> dict:
        model_selection = trajectory_eval.get("model_selection")
        if not isinstance(model_selection, dict):
            return trajectory_eval
        feedback = model_selection.get("capability_feedback")
        feedback = feedback if isinstance(feedback, dict) else {}
        summarized_feedback = {
            "status": feedback.get("status", "unknown"),
            "decision": feedback.get("decision", "unknown"),
            "blocking_count": feedback.get("blocking_count", 0),
            "review_count": feedback.get("review_count", 0),
            "active_next_step": capability_feedback_active_next_step(feedback),
        }
        summarized_selection = {
            "purpose": model_selection.get("purpose"),
            "selected_tier": model_selection.get("selected_tier"),
            "reason": model_selection.get("reason"),
            "tier_pressure": model_selection.get("tier_pressure") or {},
            "capability_feedback": summarized_feedback,
        }
        return {
            **trajectory_eval,
            "model_selection": summarized_selection,
        }

    def _failure_classification_lines(self, eval_report: dict) -> list[str]:
        classification = (
            eval_report.get("failure_classification")
            or (eval_report.get("trajectory_eval") or {}).get("failure_classification")
            or {}
        )
        if not classification:
            return ["- Category: unknown", "- Recommended command: debug"]
        return [
            f"- Category: {classification.get('category', 'unknown')}",
            f"- Recommended command: asteria {classification.get('recommended_command', 'debug')}",
            f"- Reason: {classification.get('reason', 'No reason recorded.')}",
        ]

    def _human_next_actions(
        self, eval_report: dict, action_plan: dict, blockers: list[str]
    ) -> list[str]:
        if not blockers and eval_report["overall"].get("status") == "pass":
            return ["Run `asteria accept` to finalize accepted work."]
        actions = []
        recommended = action_plan.get("recommended_route") or action_plan.get("recommended_action")
        if recommended and recommended != "continue":
            actions.append(f"Follow observation action: {recommended}.")
        if eval_report["overall"].get("status") != "pass":
            actions.append("Run `asteria debug` or `asteria replan`, then rerun `asteria review`.")
        if not actions:
            actions.append("Inspect blockers and rerun review after repair.")
        return actions[:5]

    def _latest_plan_reason(self, action_plan: dict) -> str:
        blockers = [str(item) for item in action_plan.get("blockers") or [] if item]
        route = action_plan.get("recommended_route") or action_plan.get("recommended_action")
        if blockers:
            return f"{route or 'continue'}: {blockers[0]}"
        return "No blocker summary available."

    def _latest_plan_evidence(self, action_plan: dict) -> str:
        refs = [str(item) for item in action_plan.get("evidence_refs") or [] if item]
        if refs:
            return ", ".join(refs[:3])
        plan_id = action_plan.get("observation_plan_id")
        if plan_id:
            return str(plan_id)
        return "No evidence refs recorded."

    def _json(self, value: dict) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)

    def _model_client(self, run_dir: Path, budget: BudgetController) -> ModelClient:
        if self.model_client:
            return MeteredModelClient(
                self.model_client,
                budget,
                ModelCallLogger(run_dir, self.validator),
            )
        return create_model_client(run_dir, self.validator, budget)

    def _write_active_goal_memory(
        self,
        *,
        run_dir: Path,
        run_status: dict,
        review_status: str,
        completion: str,
        blockers: list[str],
        next_actions: list[str],
    ) -> Path | None:
        goal_path = run_dir / "goal_spec.json"
        task_path = run_dir / "task_plan.json"
        if not goal_path.exists() or not task_path.exists():
            return None
        pending_decisions = self._decisions_with_status(run_dir, {"pending"})
        accepted_decisions = self._decisions_with_status(run_dir, {"resolved", "defaulted"})
        return ActiveGoalMemory(self.root).write_from_run(
            goal_spec=self.store.read(goal_path, "goal_spec"),
            task_plan=self.store.read(task_path, "task_board"),
            run_status=run_status,
            review_status=review_status,
            completion=completion,
            blockers=blockers,
            next_actions=next_actions,
            artifacts=[str(run_dir / "eval_report.json"), str(run_dir / "review_report.md")],
            pending_decisions=pending_decisions,
            accepted_decisions=accepted_decisions,
            updated_by="review",
            update_reason="review_passed" if review_status == "pass" else "review_blocked",
        )

    def _decisions_with_status(self, run_dir: Path, statuses: set[str]) -> list[dict]:
        decisions_path = run_dir / "decisions.jsonl"
        if not decisions_path.exists():
            return []
        return [
            decision
            for decision in self.jsonl.read_all(decisions_path, "decision_point")
            if decision.get("status") in statuses
        ]

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

    def _read_jsonl(self, path: Path, schema_name: str) -> list[dict]:
        if not path.exists():
            return []
        return self.jsonl.read_all(path, schema_name)

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted(
            [path for path in runs_dir.iterdir() if path.is_dir()],
            key=lambda item: item.name,
        )
        return runs[-1].name if runs else None
