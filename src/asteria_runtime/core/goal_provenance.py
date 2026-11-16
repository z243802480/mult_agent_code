"""Producer facts for goal interpretations, never a permission or semantic verdict."""

from asteria_runtime.core.verification_revision import authority_digest


def proposal_origin(goal: dict, kind: str = "model_proposal") -> dict:
    payload = {k: v for k, v in goal.items() if k != "proposal_origin"}
    return {
        "producer": "goal_spec_agent", "kind": kind,
        "goal_id": goal["goal_id"],
        "original_goal_sha256": authority_digest(goal["original_goal"]),
        "proposal_sha256": authority_digest(payload),
    }


def proposal_origin_status(goal: dict) -> str:
    record = goal.get("proposal_origin")
    if not isinstance(record, dict) or record.get("kind") not in {"model_proposal", "runtime_fallback"}:
        return "unverified"
    if not isinstance(goal.get("original_goal"), str) or not isinstance(goal.get("goal_id"), str):
        return "unverified"
    return "verified" if record == proposal_origin(goal, record["kind"]) else "unverified"
