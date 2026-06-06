from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.promotions_command import PromotionsCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.run_command import RunCommand, RunStepSummary
from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.long_horizon_completion import evaluate_and_persist_slice_completion
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class AcceptResult:
    run_id: str
    status: str
    accepted: bool
    review_status: str
    final_report_path: Path
    final_report_summary_path: Path | None = None
    final_report_summary: dict = field(default_factory=dict)
    promoted_files: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    recommended_next_command: str | None = None

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "status": self.status,
            "accepted": self.accepted,
            "review_status": self.review_status,
            "final_report_path": str(self.final_report_path),
            "final_report_summary_path": (
                str(self.final_report_summary_path) if self.final_report_summary_path else None
            ),
            "final_report_summary": self.final_report_summary,
            "promoted_files": self.promoted_files,
            "blockers": self.blockers,
            "primary_blocker": self.primary_blocker,
            "next_actions": self.next_actions,
            "recommended_next_command": self.recommended_next_command,
        }

    @property
    def primary_blocker(self) -> str | None:
        for blocker in self.blockers:
            if "review status" in blocker:
                return blocker
        return self.blockers[0] if self.blockers else None

    def to_text(self) -> str:
        lines = [
            f"Accept: {'accepted' if self.accepted else 'blocked'}",
            f"Run: {self.run_id}",
            f"Status: {self.status}",
            f"Review status: {self.review_status}",
            f"Final report: {self.final_report_path}",
        ]
        if self.final_report_summary_path:
            lines.append(f"Final report summary: {self.final_report_summary_path}")
        if self.final_report_summary:
            selection = self.final_report_summary.get("model_selection") or {}
            if selection:
                lines.append(
                    "Model selection: "
                    f"{selection.get('selected_tier', 'unknown')} "
                    f"({selection.get('reason', 'no reason recorded')})"
                )
        if self.promoted_files:
            lines.append("Promoted files:")
            lines.extend(f"- {path}" for path in self.promoted_files)
        if self.blockers:
            lines.append(f"Primary blocker: {self.primary_blocker}")
            lines.append("Blockers:")
            lines.extend(f"- {item}" for item in self.blockers)
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {item}" for item in self.next_actions)
        if self.recommended_next_command:
            lines.append(f"Recommended next command: asteria {self.recommended_next_command}")
        return "\n".join(lines)


class AcceptCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        *,
        skip_review: bool = False,
        promote_all: bool = True,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.skip_review = skip_review
        self.promote_all = promote_all
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> AcceptResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError('No current session found. Run `asteria run "goal"` first.')
        run_dir = run_store.run_dir(run_id)
        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
        progress.record(
            run_id=run_id,
            channel="progress",
            phase="review",
            status="running",
            title="开始验收收尾",
            summary="正在检查评审状态、候选 promotion 和最终报告落点。",
            display_level="main",
            call_chain=["AcceptCommand"],
            execution_chain=["accept", "preflight"],
            transcript_kind="verification",
            ui_intent="work_progress",
        )

        review_status = self._latest_review_status(run_dir)
        if not self.skip_review and review_status != "pass":
            review = ReviewCommand(self.root, run_id=run_id).run()
            review_status = review.status

        blockers: list[str] = []
        promoted_files: list[str] = []
        pending = self._pending_promotions(run_dir)
        if pending and self.promote_all:
            progress.record(
                run_id=run_id,
                channel="progress",
                phase="execute",
                status="running",
                title="正在处理候选 promotion",
                summary=f"发现 {len(pending)} 个待处理候选，正在尝试批准并合并。",
                display_level="main",
                data={"pending_promotions": len(pending), "promote_all": self.promote_all},
                call_chain=["AcceptCommand", "PromotionsCommand"],
                execution_chain=["accept", "promotion"],
                transcript_kind="verification",
                ui_intent="work_progress",
            )
            promotion_result = PromotionsCommand(
                self.root,
                run_id=run_id,
                action="approve",
                all_pending=True,
                reason="Accepted by operator.",
            ).run()
            for promotion in promotion_result.promotions:
                if promotion.get("status") == "promoted":
                    promoted_files.extend(
                        str(path) for path in promotion.get("promoted_files") or []
                    )
                else:
                    failure = promotion.get("failure") or {}
                    blockers.append(
                        f"promotion {promotion.get('promotion_id')} {promotion.get('status')}: "
                        f"{failure.get('message') or 'not promoted'}"
                    )
        elif pending:
            blockers.append(
                f"{len(pending)} pending promotion(s) require approval; run `asteria accept` "
                "without --no-promote or use `asteria promotions approve`."
            )

        if review_status != "pass":
            blockers.append(
                f"review status is {review_status}; run `asteria review` or repair follow-ups."
            )

        pending_after = self._pending_promotions(run_dir)
        if pending_after:
            blockers.append(f"{len(pending_after)} promotion(s) still block acceptance.")

        accepted = not blockers
        run = run_store.load_run(run_id)
        if accepted:
            run["status"] = "completed"
            run["current_phase"] = "ACCEPTED"
            run["ended_at"] = now_iso()
            run["summary"] = (
                "Accepted by operator; review passed and candidate promotions are settled."
            )
        else:
            run["status"] = "blocked"
            run["current_phase"] = "ACCEPT"
            run["summary"] = "Acceptance blocked; review or candidate promotion issues remain."
        run_store.update_run(run)
        north_star_link = None
        slice_completion_eval = None
        goal_queue_continue = None
        north_star_store = NorthStarStore(self.root, self.validator)
        if accepted and north_star_store.exists():
            north_star_link = north_star_store.link_run(run_id)
            slice_completion_eval = evaluate_and_persist_slice_completion(
                self.root,
                run_id,
                validator=self.validator,
                accepted=accepted,
                review_status=review_status,
                north_star_link=north_star_link,
            )
            GoalQueueStore(self.root, self.validator).mark_done_for_run(run_id)
            goal_queue_continue = GoalQueueStore(self.root, self.validator).continue_hint()
        final_report_path = self._write_final_report(run_id, review_status)
        next_actions = self._next_actions(
            accepted,
            blockers,
            slice_completion_eval=slice_completion_eval,
            goal_queue_continue=goal_queue_continue,
        )
        recommended_next_command = self._recommended_next_command(
            accepted,
            blockers,
            goal_queue_continue=goal_queue_continue,
        )
        final_report_summary_path = self._write_final_report_summary(
            run_id=run_id,
            status=run["status"],
            review_status=review_status,
            final_report_path=final_report_path,
            blockers=blockers,
            next_actions=next_actions,
            recommended_next_command=recommended_next_command,
        )
        final_report_summary = JsonStore(self.validator).read(
            final_report_summary_path,
            "final_report_summary",
        )
        RunCommand(self.root)._write_run_loop_summary(
            run_id=run_id,
            steps=[RunStepSummary("accept", "completed", "Operator accepted the reviewed result.")],
            status_payload={
                "workflow_state": "accepted" if accepted else "blocked",
                "current_blocker": blockers[0] if blockers else None,
                "recommended_next_command": recommended_next_command,
                "blockers": blockers,
                "next_actions": next_actions,
            },
            stop_reason="accepted" if accepted else "accept_blocked",
        )
        RunCommand(self.root)._write_active_goal_memory(
            run_id=run_id,
            review_status=review_status,
            steps=[RunStepSummary("accept", "completed", "Operator accepted the reviewed result.")],
            blockers=blockers,
            next_actions=next_actions,
        )
        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            "run_accepted" if accepted else "accept_blocked",
            "AcceptCommand",
            run["summary"],
            {
                "review_status": review_status,
                "promoted_files": promoted_files,
                "blockers": blockers,
                "final_report_summary_path": str(final_report_summary_path),
                "north_star_link": north_star_link,
                "slice_completion_eval": slice_completion_eval,
                "goal_queue_continue": goal_queue_continue,
            },
        )
        if slice_completion_eval:
            progress.record(
                run_id=run_id,
                channel="conclusion",
                event_type="message",
                phase="result",
                status="completed" if slice_completion_eval.get("slice_complete") else "blocked",
                title="本 slice 完成判定",
                summary=str(slice_completion_eval.get("summary") or ""),
                data={
                    "slice_complete": slice_completion_eval.get("slice_complete"),
                    "signals": slice_completion_eval.get("signals") or {},
                    "north_star_milestone_id": slice_completion_eval.get("north_star_milestone_id"),
                },
                display_level="main",
                transcript_kind="final",
            )
        if goal_queue_continue:
            progress.record(
                run_id=run_id,
                channel="progress",
                event_type="message",
                phase="next",
                status="waiting_user",
                title="North Star 下一条 slice",
                summary=(
                    f"建议继续：{goal_queue_continue.get('goal_text')} "
                    f"（运行 `asteria {goal_queue_continue.get('command')}`）"
                ),
                data=goal_queue_continue,
                display_level="main",
                transcript_kind="ask",
                ui_intent="needs_input",
            )
        progress.final_report_event(
            run_id=run_id,
            title="验收报告已写入",
            summary=(
                "验收已通过，最终报告可作为交付记录。"
                if accepted
                else "验收被阻塞，最终报告已记录阻塞原因和下一步。"
            ),
            final_report_path=str(final_report_path),
            final_report_summary_path=str(final_report_summary_path),
            output_locations=final_report_summary.get("output_locations") or {},
            validation={
                "accepted": accepted,
                "review_status": review_status,
                "blockers": blockers,
            },
        )
        progress.conclusion(
            run_id=run_id,
            phase="result" if accepted else "blocked",
            title="验收完成" if accepted else "验收受阻",
            summary=run["summary"],
            content_delta="\n".join(next_actions),
            artifact_refs=[str(final_report_path), str(final_report_summary_path)],
        )

        return AcceptResult(
            run_id=run_id,
            status=run["status"],
            accepted=accepted,
            review_status=review_status,
            final_report_path=final_report_path,
            final_report_summary_path=final_report_summary_path,
            final_report_summary=final_report_summary,
            promoted_files=sorted(set(promoted_files)),
            blockers=blockers,
            next_actions=next_actions,
            recommended_next_command=recommended_next_command,
        )

    def _latest_review_status(self, run_dir: Path) -> str:
        path = run_dir / "eval_report.json"
        if not path.exists():
            return "unknown"
        return str(RunCommand(self.root)._latest_review_status(run_dir.name))

    def _pending_promotions(self, run_dir: Path) -> list[dict]:
        summary = CandidatePromotionQueue(self.validator).summary(run_dir)
        return list(summary.get("pending") or []) + list(summary.get("blocked") or [])

    def _write_final_report(self, run_id: str, review_status: str) -> Path:
        return RunCommand(self.root)._write_final_report(
            run_id,
            review_status,
            [RunStepSummary("accept", "completed", "Operator acceptance workflow executed.")],
        )

    def _write_final_report_summary(
        self,
        *,
        run_id: str,
        status: str,
        review_status: str,
        final_report_path: Path,
        blockers: list[str],
        next_actions: list[str],
        recommended_next_command: str | None,
    ) -> Path:
        return RunCommand(self.root)._write_final_report_summary(
            run_id=run_id,
            status=status,
            review_status=review_status,
            final_report_path=final_report_path,
            status_payload={
                "workflow_state": "accepted" if not blockers else "blocked",
                "current_blocker": blockers[0] if blockers else None,
                "recommended_next_command": recommended_next_command,
                "blockers": blockers,
                "next_actions": next_actions,
            },
        )

    def _next_actions(
        self,
        accepted: bool,
        blockers: list[str],
        *,
        slice_completion_eval: dict | None = None,
        goal_queue_continue: dict | None = None,
    ) -> list[str]:
        if accepted:
            actions = ["Use the final report as the durable handoff artifact."]
            if slice_completion_eval:
                actions.append(str(slice_completion_eval.get("summary") or "Slice completion evaluated."))
            if goal_queue_continue:
                actions.append(
                    "Continue North Star: "
                    f"`asteria {goal_queue_continue.get('command')}`"
                )
            return actions
        actions = ["Inspect blockers above before release or handoff."]
        if any("review status" in blocker for blocker in blockers):
            actions.append("Run `asteria debug` or `asteria replan`, then `asteria review`.")
        if any("promotion" in blocker for blocker in blockers):
            actions.append(
                "Run `asteria promotions list` and approve, reject, retry, or discard blockers."
            )
        return actions

    def _recommended_next_command(
        self,
        accepted: bool,
        blockers: list[str],
        *,
        goal_queue_continue: dict | None = None,
    ) -> str | None:
        if accepted:
            if goal_queue_continue and goal_queue_continue.get("command"):
                return str(goal_queue_continue["command"])
            return None
        if any("review status" in blocker for blocker in blockers):
            return "debug"
        if any("promotion" in blocker for blocker in blockers):
            return "promotions list"
        return "status"
