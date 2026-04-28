from __future__ import annotations

import json

from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.models.model_call_logger import ModelCallLogger


class FakeModelClient:
    """Deterministic offline model for CLI smoke tests and reproducible demos."""

    def __init__(self, logger: ModelCallLogger | None = None) -> None:
        self.logger = logger

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self._payload(request)
        content = json.dumps(payload, ensure_ascii=False)
        response = ChatResponse(
            content=content,
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=self._estimate_tokens(request),
                output_tokens=max(1, len(content) // 4),
                total_tokens=None,
                usage_estimated=True,
            ),
            model_provider="fake",
            model_name="fake-offline",
            raw_response={"purpose": request.purpose},
        )
        if self.logger:
            self.logger.record_success(request, response)
        return response

    def _payload(self, request: ChatRequest) -> dict:
        if request.purpose == "model_check":
            return {"ok": True}
        if request.purpose == "goal_spec":
            return self._goal_spec(request)
        if request.purpose in {"task_execution", "task_repair"}:
            return self._execution_action(request)
        if request.purpose == "run_review":
            return self._eval_report(request)
        if request.purpose == "research":
            return self._research_report(request)
        if request.purpose == "brainstorming":
            return self._brainstorm_report(request)
        return {"ok": True, "purpose": request.purpose}

    def _goal_spec(self, request: ChatRequest) -> dict:
        prompt = request.messages[-1].content
        goal = self._extract_goal(prompt)
        return {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": f"Deliver offline artifact for: {goal}",
            "goal_type": "software_tool",
            "assumptions": ["offline deterministic fake model is acceptable for verification"],
            "constraints": ["local_first", "no_network"],
            "non_goals": ["real model quality evaluation"],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": "Create an offline verification artifact",
                    "source": "inferred",
                    "acceptance": ["offline_artifact.txt exists"],
                }
            ],
            "target_outputs": ["file"],
            "definition_of_done": ["offline_artifact.txt exists", "verification passes"],
            "verification_strategy": ["filesystem smoke check"],
            "budget": {"max_iterations": 8, "max_model_calls": 60},
        }

    def _execution_action(self, request: ChatRequest) -> dict:
        payload = json.loads(request.messages[-1].content)
        task = payload["task"]
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Create offline verification artifact.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "offline_artifact.txt",
                        "content": "offline verification artifact\n",
                        "overwrite": True,
                    },
                    "reason": "create deterministic artifact",
                }
            ],
            "verification": [
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            "python -c \"from pathlib import Path; "
                            "assert Path('offline_artifact.txt').exists()\""
                        )
                    },
                    "reason": "verify deterministic artifact",
                }
            ],
            "completion_notes": "offline_artifact.txt exists",
        }

    def _eval_report(self, request: ChatRequest) -> dict:
        context = json.loads(request.messages[-1].content)
        run_id = context["run_id"]
        checks = context.get("deterministic_checks", {})
        completion = float(checks.get("task_completion_rate", 0))
        blocked = int(checks.get("blocked_task_count", 0))
        verification = float(checks.get("verification_pass_rate", 0))
        passed = completion >= 1.0 and blocked == 0 and verification >= 1.0
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "goal_eval": {"goal_clarity_score": 0.9, "requirement_coverage": completion},
            "artifact_eval": {"artifacts_present": completion >= 1.0, "logs_present": True},
            "outcome_eval": {"verification_pass_rate": verification, "run_success": passed},
            "trajectory_eval": {"blocked_task_count": blocked, "repair_success_rate": 1.0},
            "cost_eval": {
                "status": checks.get("cost_status", "within_budget"),
                "model_calls": context.get("cost_report", {}).get("model_calls", 0),
                "tool_calls": context.get("cost_report", {}).get("tool_calls", 0),
            },
            "overall": {
                "status": "pass" if passed else "partial",
                "score": 0.92 if passed else 0.65,
                "reason": (
                    "Offline fake model run is complete and verified."
                    if passed
                    else "Offline fake model run still has incomplete work."
                ),
            },
        }

    def _research_report(self, request: ChatRequest) -> dict:
        payload = json.loads(request.messages[-1].content)
        sources = payload.get("sources", [])
        return {
            "schema_version": "0.1.0",
            "run_id": payload.get("run_id"),
            "query": payload.get("query", ""),
            "created_at": "2026-04-28T00:00:00+08:00",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "title": source["title"],
                    "source_type": source["source_type"],
                    "reference": source["reference"],
                    "summary": source["summary"],
                }
                for source in sources
            ],
            "claims": [
                {
                    "claim": "Local documentation can seed deterministic planning.",
                    "source_ids": [sources[0]["source_id"]] if sources else [],
                    "confidence": "medium",
                }
            ],
            "expanded_requirements": [
                {
                    "description": "Preserve offline deterministic verification.",
                    "priority": "should",
                    "source_ids": [sources[0]["source_id"]] if sources else [],
                }
            ],
            "risks": [],
            "decision_candidates": [],
            "summary": "Offline fake research synthesized local sources.",
        }

    def _brainstorm_report(self, request: ChatRequest) -> dict:
        payload = json.loads(request.messages[-1].content)
        goal = payload.get("goal", "offline verification")
        return {
            "schema_version": "0.1.0",
            "run_id": payload.get("run_id"),
            "goal": goal,
            "created_at": "2026-04-28T00:00:00+08:00",
            "candidates": [
                {
                    "candidate_id": "candidate-0001",
                    "title": "Offline artifact workflow",
                    "description": "Create a deterministic local artifact with verification and reporting.",
                    "scores": {
                        "goal_fit": 0.9,
                        "feasibility": 0.95,
                        "cost": 0.2,
                        "user_value": 0.75,
                        "risk": 0.1,
                        "novelty": 0.2,
                        "verification_difficulty": 0.2,
                    },
                    "risks": ["Fake model quality is not representative of production models."],
                }
            ],
            "recommendation": {
                "candidate_id": "candidate-0001",
                "reason": "It is deterministic, local-first, and easy to verify.",
            },
            "task_candidates": [
                {
                    "title": "Create offline verification artifact",
                    "description": "Create and verify a deterministic offline artifact for the goal.",
                    "priority": "high",
                    "role": "CoderAgent",
                    "acceptance": ["offline_artifact.txt exists", "local verification passes"],
                    "expected_artifacts": ["offline_artifact.txt"],
                }
            ],
            "decision_candidates": [
                {
                    "question": "Should the offline artifact flow remain local-only?",
                    "recommended_option_id": "local_only",
                    "default_option_id": "local_only",
                    "options": [
                        {
                            "option_id": "local_only",
                            "label": "Keep local only",
                            "tradeoff": "Fast and private, but does not test network research.",
                            "action": "record_constraint",
                        },
                        {
                            "option_id": "allow_research",
                            "label": "Allow research later",
                            "tradeoff": "Improves realism, but needs explicit network policy.",
                            "action": "require_replan",
                        },
                    ],
                    "impact": {"scope": "medium", "budget": "medium", "risk": "medium", "quality": "medium"},
                }
            ],
            "summary": "Offline fake brainstorming produced one local-first recommendation.",
        }

    def _extract_goal(self, prompt: str) -> str:
        marker = "User goal:"
        if marker not in prompt:
            return "offline verification"
        after_marker = prompt.split(marker, 1)[1]
        return after_marker.split("Project context:", 1)[0].strip() or "offline verification"

    def _estimate_tokens(self, request: ChatRequest) -> int:
        return max(1, sum(len(message.content) for message in request.messages) // 4)
