from __future__ import annotations

import base64
import json
import re

from asteria_runtime.core.budget import BudgetController, BudgetExceededError
from asteria_runtime.core.context_budget import estimate_request_context
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.models.model_progress_sink import model_progress_sink
from asteria_runtime.models.studio_event_sink import studio_model_event_sink


class FakeModelClient:
    """Deterministic offline model for CLI smoke tests and reproducible demos."""

    def __init__(
        self,
        logger: ModelCallLogger | None = None,
        budget: BudgetController | None = None,
    ) -> None:
        self.logger = logger
        self.budget = budget

    def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            if self.budget:
                estimate = estimate_request_context(request)
                self.budget.record_context_estimate(
                    estimate.total_tokens,
                    sections=estimate.sections,
                    duplicate_content_hashes=estimate.duplicate_content_hashes,
                )
                self.budget.record_model_call(request.model_tier)
        except BudgetExceededError as exc:
            if self.logger:
                self.logger.record_failure(
                    request,
                    provider="fake",
                    model_name="fake-offline",
                    model_tier=request.model_tier,
                    error=str(exc),
                )
            raise

        if self.logger:
            progress_context = self.logger.progress_context(request)
        else:
            progress_context = None
        if progress_context is None:
            payload = self._payload(request)
        else:
            with progress_context:
                sink = model_progress_sink()
                studio_sink = studio_model_event_sink()
                sink.model_start(provider="fake", model="fake-offline", mode="non_streaming")
                studio_sink.model_start(provider="fake", model="fake-offline", mode="non_streaming")
                payload = self._payload(request)
                preview = json.dumps(payload, ensure_ascii=False)
                sink.model_delta(preview, provider="fake", model="fake-offline")
                studio_sink.model_delta(preview, provider="fake", model="fake-offline")
                sink.model_end(
                    provider="fake",
                    model="fake-offline",
                    telemetry={"mode": "non_streaming", "usage_estimated": True},
                )
                studio_sink.model_end(
                    provider="fake",
                    model="fake-offline",
                    telemetry={"mode": "non_streaming", "usage_estimated": True},
                )
        content = json.dumps(payload, ensure_ascii=False)
        usage = TokenUsage(
            input_tokens=self._estimate_tokens(request),
            output_tokens=max(1, len(content) // 4),
            total_tokens=None,
            usage_estimated=True,
        )
        if self.budget:
            self.budget.record_model_tokens(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        response = ChatResponse(
            content=content,
            finish_reason="stop",
            usage=usage,
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
        if request.purpose == "slice_completion_judge":
            return self._slice_completion_judge(request)
        if request.purpose == "research":
            return self._research_report(request)
        if request.purpose == "brainstorming":
            return self._brainstorm_report(request)
        return {"ok": True, "purpose": request.purpose}

    def _goal_spec(self, request: ChatRequest) -> dict:
        prompt = request.messages[-1].content
        goal = self._extract_goal(prompt)
        contract = self._goal_contract(goal)
        return {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": f"Deliver deterministic fake artifact for: {goal}",
            "goal_type": "software_tool",
            "assumptions": ["offline deterministic fake model is acceptable for verification"],
            "constraints": ["local_first", "no_network"],
            "non_goals": ["real model quality evaluation"],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": contract["description"],
                    "source": "inferred",
                    "acceptance": contract["acceptance"],
                    "expected_artifacts": [contract["path"]],
                }
            ],
            "target_outputs": [contract["path"]],
            "definition_of_done": contract["definition_of_done"],
            "verification_strategy": [contract["verification_command"]],
            "budget": {"max_iterations": 8, "max_model_calls": 60},
        }

    def _execution_action(self, request: ChatRequest) -> dict:
        payload = json.loads(request.messages[-1].content)
        task = payload["task"]
        target_paths = self._task_target_paths(task)
        tool_calls = []
        for path in target_paths:
            content = self._content_for_task_path(task, path)
            tool_calls.append(
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": path,
                        "content": content,
                        "overwrite": True,
                    },
                    "reason": "satisfy declared fake-model file contract",
                }
            )
        verification = []
        if target_paths:
            path = target_paths[0]
            content = self._content_for_task_path(task, path)
            verification.append(
                {
                    "tool_name": "run_command",
                    "args": {"command": self._verification_command(path, content.strip())},
                    "reason": "verify deterministic fake artifact",
                }
            )
        return {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": "Create deterministic fake artifact.",
            "tool_calls": tool_calls,
            "verification": verification,
            "completion_notes": f"{target_paths[0]} exists" if target_paths else "no artifact target",
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

    def _slice_completion_judge(self, request: ChatRequest) -> dict:
        prompt = request.messages[-1].content
        try:
            context = json.loads(prompt)
        except json.JSONDecodeError:
            context = {}
        open_tasks = context.get("open_tasks") if isinstance(context.get("open_tasks"), list) else []
        if open_tasks:
            return {
                "slice_complete": False,
                "confidence": 0.88,
                "reason": f"Open tasks remain: {', '.join(str(item) for item in open_tasks[:3])}.",
            }
        if not context.get("rule_slice_complete"):
            return {
                "slice_complete": False,
                "confidence": 0.9,
                "reason": "Rule-based completion signals are not satisfied.",
            }
        return {
            "slice_complete": True,
            "confidence": 0.86,
            "reason": "North Star slice acceptance criteria appear satisfied.",
        }

    def _research_report(self, request: ChatRequest) -> dict:
        payload = json.loads(request.messages[-1].content)
        sources = payload.get("sources", [])
        return {
            "schema_version": "0.1.0",
            "run_id": payload.get("run_id"),
            "query": payload.get("query", ""),
            "research_type": payload.get("research_type", "general"),
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
            "design_brief": {
                "problem": "Use local research sources to guide implementation.",
                "observed_patterns": ["Offline source-grounded synthesis"],
                "asteria_adaptation": ["Keep research reports tied to local evidence."],
                "do_not_copy": [],
                "open_questions": [],
            },
            "pattern_candidates": [],
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

    def _goal_contract(self, goal: str) -> dict:
        path = (
            self._extract_output_path(goal)
            or self._extract_first_path(goal)
            or "offline_artifact.txt"
        )
        content = self._content_for_goal(goal, path)
        return {
            "path": path,
            "description": f"Create or update {path} with deterministic fake-model content.",
            "acceptance": [
                f"{path} exists",
                f"{path} contains {content.strip()!r}",
                "local verification passes",
            ],
            "definition_of_done": [f"{path} exists", f"{path} contains {content.strip()!r}"],
            "verification_command": self._verification_command(path, content.strip()),
        }

    def _extract_output_path(self, text: str) -> str | None:
        match = re.search(
            r"\b(?:create|write|update)\s+([\w./-]+\.(?:py|md|txt|json|html|css|js|ts|tsx|pdf))",
            text,
            flags=re.I,
        )
        return match.group(1).replace("\\", "/") if match else None

    def _extract_first_path(self, text: str) -> str | None:
        match = re.search(
            r"[\w./-]+\.(?:py|md|txt|json|html|css|js|ts|tsx|pdf)",
            text,
            flags=re.I,
        )
        return match.group(0).replace("\\", "/") if match else None

    def _content_for_goal(self, goal: str, path: str) -> str:
        lowered = goal.lower()
        if path.endswith("calc.py") and "add(2, 3) returns 5" in lowered:
            return "def add(a, b):\n    return a + b\n"
        if path.endswith("repair_target.py") and "status() returns 'fixed'" in lowered:
            return "def status():\n    return 'fixed'\n"
        explicit = self._extract_content_phrase(goal)
        if explicit:
            if path.endswith(".md") and "heading" in lowered:
                return f"# {explicit}\n\n- Review real-provider smoke evidence.\n"
            return explicit.rstrip() + "\n"
        if path.endswith(".md"):
            title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").title()
            return f"# {title}\n\n- Fake model deterministic artifact.\n"
        return "offline verification artifact\n"

    def _extract_content_phrase(self, text: str) -> str | None:
        patterns = [
            r"containing one line:\s*(.+)$",
            r"containing:\s*(.+)$",
            r"containing\s+(.+)$",
            r"with the heading\s+(.+?)(?:\s+and\s+|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.S)
            if match:
                return " ".join(match.group(1).strip().strip("\"'").split())
        return None

    def _task_target_paths(self, task: dict) -> list[str]:
        paths: list[str] = []
        for field in ("expected_changed_files", "expected_artifacts", "write_scope"):
            for item in task.get(field) or []:
                if not isinstance(item, str):
                    continue
                path = item.replace("\\", "/")
                if not self._extract_first_path(path):
                    continue
                if path not in paths:
                    paths.append(path)
        return paths or ["offline_artifact.txt"]

    def _content_for_task_path(self, task: dict, path: str) -> str:
        text = " ".join(
            [
                str(task.get("description") or ""),
                " ".join(str(item) for item in task.get("acceptance") or []),
            ]
        )
        quoted_contains = re.search(r"contains\s+(['\"])(.+?)\1", text, flags=re.I | re.S)
        if quoted_contains:
            return quoted_contains.group(2).replace("\\n", "\n").rstrip() + "\n"
        return self._content_for_goal(text, path)

    def _verification_command(self, path: str, expected_text: str) -> str:
        encoded = base64.b64encode(expected_text.encode("utf-8")).decode("ascii")
        return (
            "python -c \"from pathlib import Path; import base64; "
            f"p=Path({path!r}); assert p.exists(); "
            f"expected=base64.b64decode({encoded!r}).decode('utf-8'); "
            "assert expected in p.read_text(encoding='utf-8')\""
        )

    def _estimate_tokens(self, request: ChatRequest) -> int:
        return max(1, sum(len(message.content) for message in request.messages) // 4)
