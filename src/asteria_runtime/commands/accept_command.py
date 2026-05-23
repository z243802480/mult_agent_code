from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.promotions_command import PromotionsCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.run_command import RunCommand, RunStepSummary
from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class AcceptResult:
    run_id: str
    status: str
    accepted: bool
    review_status: str
    final_report_path: Path
    promoted_files: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "run_id": self.run_id,
            "status": self.status,
            "accepted": self.accepted,
            "review_status": self.review_status,
            "final_report_path": str(self.final_report_path),
            "promoted_files": self.promoted_files,
            "blockers": self.blockers,
            "next_actions": self.next_actions,
        }

    def to_text(self) -> str:
        lines = [
            f"Accept: {'accepted' if self.accepted else 'blocked'}",
            f"Run: {self.run_id}",
            f"Status: {self.status}",
            f"Review status: {self.review_status}",
            f"Final report: {self.final_report_path}",
        ]
        if self.promoted_files:
            lines.append("Promoted files:")
            lines.extend(f"- {path}" for path in self.promoted_files)
        if self.blockers:
            lines.append("Blockers:")
            lines.extend(f"- {item}" for item in self.blockers)
        if self.next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {item}" for item in self.next_actions)
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

        review_status = self._latest_review_status(run_dir)
        if not self.skip_review and review_status != "pass":
            review = ReviewCommand(self.root, run_id=run_id).run()
            review_status = review.status

        blockers: list[str] = []
        promoted_files: list[str] = []
        pending = self._pending_promotions(run_dir)
        if pending and self.promote_all:
            promotion_result = PromotionsCommand(
                self.root,
                run_id=run_id,
                action="approve",
                all_pending=True,
                reason="Accepted by operator.",
            ).run()
            for promotion in promotion_result.promotions:
                if promotion.get("status") == "promoted":
                    promoted_files.extend(str(path) for path in promotion.get("promoted_files") or [])
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
            blockers.append(f"review status is {review_status}; run `asteria review` or repair follow-ups.")

        pending_after = self._pending_promotions(run_dir)
        if pending_after:
            blockers.append(f"{len(pending_after)} promotion(s) still block acceptance.")

        final_report_path = self._write_final_report(run_id, review_status)
        accepted = not blockers
        run = run_store.load_run(run_id)
        if accepted:
            run["status"] = "completed"
            run["current_phase"] = "ACCEPTED"
            run["ended_at"] = now_iso()
            run["summary"] = "Accepted by operator; review passed and candidate promotions are settled."
        else:
            run["status"] = "blocked"
            run["current_phase"] = "ACCEPT"
            run["summary"] = "Acceptance blocked; review or candidate promotion issues remain."
        run_store.update_run(run)
        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            "run_accepted" if accepted else "accept_blocked",
            "AcceptCommand",
            run["summary"],
            {"review_status": review_status, "promoted_files": promoted_files, "blockers": blockers},
        )

        return AcceptResult(
            run_id=run_id,
            status=run["status"],
            accepted=accepted,
            review_status=review_status,
            final_report_path=final_report_path,
            promoted_files=sorted(set(promoted_files)),
            blockers=blockers,
            next_actions=self._next_actions(accepted, blockers),
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

    def _next_actions(self, accepted: bool, blockers: list[str]) -> list[str]:
        if accepted:
            return ["Use the final report as the durable handoff artifact."]
        actions = ["Inspect blockers above before release or handoff."]
        if any("review status" in blocker for blocker in blockers):
            actions.append("Run `asteria debug` or `asteria replan`, then `asteria review`.")
        if any("promotion" in blocker for blocker in blockers):
            actions.append("Run `asteria promotions list` and approve, reject, retry, or discard blockers.")
        return actions
