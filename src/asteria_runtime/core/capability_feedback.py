from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class CapabilityFeedbackAdvisor:
    validator: SchemaValidator
    max_hints: int = 5

    def planner_hints(self, agent_dir: Path) -> list[dict]:
        return self._actionable_hints(agent_dir)[: self.max_hints]

    def route_guidance(self, agent_dir: Path) -> dict:
        hints = self._actionable_hints(agent_dir)
        blocking = [item for item in hints if int(item.get("severity") or 0) >= 3]
        review = [item for item in hints if int(item.get("severity") or 0) == 2]
        status = "healthy"
        if blocking:
            status = "blocked"
        elif review:
            status = "review"
        return {
            "status": status,
            "blocking": blocking,
            "review": review,
            "recommended_actions": self._route_actions(blocking, review),
        }

    def _actionable_hints(self, agent_dir: Path) -> list[dict]:
        profile_path = agent_dir / "model" / "capability_profile.json"
        if not profile_path.exists():
            return []
        profile = JsonStore(self.validator).read(profile_path, "model_capability_profile")
        hints = [self._hint(item) for item in profile.get("profiles", []) if isinstance(item, dict)]
        actionable = [hint for hint in hints if hint]
        actionable.sort(key=lambda item: (item["severity"], item["purpose"]), reverse=True)
        return actionable

    def _hint(self, profile: dict) -> dict:
        action = str(profile.get("recommended_action") or "")
        purpose = str(profile.get("purpose") or "unknown")
        provider = str(profile.get("provider") or "unknown")
        model = str(profile.get("model") or "unknown")
        tier = str(profile.get("model_tier") or "unknown")
        if action in {"", "keep_route", "collect_more_data"}:
            return {}
        severity = 2
        if action in {"pause_route_until_config_fixed", "review_worker_route_before_scaling"}:
            severity = 3
        if action == "improve_planner_scope_before_scaling":
            message = "prefer narrower read/write scope before scaling similar tasks"
        elif action == "review_merge_quality_before_scaling":
            message = "tighten write_scope and verification before promoting similar tasks"
        elif action == "review_validation_or_route_before_scaling":
            message = "prefer stronger verification or a different route for similar tasks"
        else:
            message = action.replace("_", " ")
        return {
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "model_tier": tier,
            "recommended_action": action,
            "message": message,
            "severity": severity,
        }

    def _route_actions(self, blocking: list[dict], review: list[dict]) -> list[str]:
        if blocking:
            return [
                "Pause scaling affected routes until provider, worker, or budget issues are resolved.",
                "Run `asteria capability-report` after collecting fresh evidence.",
            ]
        if review:
            return [
                "Review affected route purposes before increasing long-run budget.",
                "Prefer smaller scoped tasks or stronger verification for matching work.",
            ]
        return ["Keep current model routes and continue collecting capability evidence."]
