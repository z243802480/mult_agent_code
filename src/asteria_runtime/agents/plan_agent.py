from __future__ import annotations

import json
from dataclasses import dataclass

from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.core.execution_profile import HARNESS, SESSION_AGENT
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class PlanAgentError(RuntimeError):
    """The model's task plan was unusable (bad JSON / wrong shape / failed schema).

    Distinct from provider/transport failures so the caller can tell "the model answered
    nonsense" (no failure report needed — the answer itself is the evidence) from "the
    provider failed" (ModelFailureRecorder report warranted)."""


MAX_PLAN_TASKS = 16


@dataclass
class PlanAgent:
    """L2 cognition (ADR-0033): GoalSpec -> tasks by one model call.

    The model decides the decomposition; RequirementPlanner.finalize_model_tasks only
    normalizes shape and applies the same contract hardening the template branch uses.
    Every failure mode raises PlanAgentError so the caller falls back to the deterministic
    planner — offline runs and CI never see a model requirement."""

    model_client: ModelClient
    validator: SchemaValidator

    def generate(
        self,
        goal_spec: dict,
        runtime_context: dict | None = None,
        run_id: str = "run-plan",
        model_tier: str = "strong",
        execution_profile: str = HARNESS,
        policy: dict | None = None,
    ) -> dict:
        runtime_context = runtime_context or {}
        role_contract = role_contract_for(
            role="PlannerAgent",
            purpose="task_planning",
            policy=policy if isinstance(policy, dict) else None,
        )
        request = ChatRequest(
            purpose="task_planning",
            model_tier=model_tier,
            messages=[
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(
                    role="user",
                    content=self._user_prompt(goal_spec, runtime_context, execution_profile),
                ),
            ],
            response_format="json",
            temperature=0.2,
            max_output_tokens=6000,
            metadata={
                "run_id": run_id,
                "agent_id": "PlannerAgent",
                "agent_role_contract": role_contract.to_dict(),
            },
        )
        response = self.model_client.chat(request)
        raw_tasks = self._parse_tasks(response.content)
        planner = RequirementPlanner()
        if execution_profile == SESSION_AGENT and len(raw_tasks) != 1:
            raise PlanAgentError(
                f"session_agent profile requires exactly one task; model returned {len(raw_tasks)}"
            )
        tasks = planner.finalize_model_tasks(
            raw_tasks,
            goal_spec,
            runtime_context,
            execution_profile=execution_profile,
        )
        for task in tasks:
            try:
                self.validator.validate("task", task)
            except SchemaValidationError as exc:
                raise PlanAgentError(
                    f"model task {task.get('task_id')} failed schema validation: {exc}"
                ) from exc
        return {"schema_version": "0.1.0", "tasks": tasks}

    def _parse_tasks(self, content: str) -> list[dict]:
        try:
            data = parse_json_object(content)
        except JsonExtractionError as exc:
            raise PlanAgentError(f"task plan response was not valid JSON: {exc}") from exc
        tasks = data.get("tasks") if isinstance(data, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise PlanAgentError("task plan response has no non-empty 'tasks' list")
        raw_tasks = [task for task in tasks if isinstance(task, dict)]
        if not raw_tasks:
            raise PlanAgentError("task plan response 'tasks' contains no task objects")
        if len(raw_tasks) > MAX_PLAN_TASKS:
            raise PlanAgentError(f"model proposed {len(raw_tasks)} tasks; cap is {MAX_PLAN_TASKS}")
        return raw_tasks

    def _system_prompt(self) -> str:
        return """You are PlannerAgent for a local-first autonomous development runtime.

Return only valid JSON matching the shape below. Do not wrap in markdown.

You decompose the given GoalSpec into an executable task plan.

You must:
- Produce 1 to 8 tasks, ordered so dependencies come before dependents. Fewer, well-chosen
  slices beat many tiny ones; if the goal is one coherent slice, return one task.
- Give every task a short verb-object title and a description naming the implementation
  slice, its behavior, and its target artifact.
- Write 1-6 acceptance criteria per task that a tool or reviewer can check — name files,
  tests, or commands. Never "works correctly" without an observable check.
- Use concrete file paths for expected_artifacts and expected_changed_files. Never list a
  pre-existing test file the task is judged by; DO list new test files the task authors.
- Reference only task ids present in this plan inside depends_on; leave it empty for entry
  tasks.
- Pick task_kind from: implementation, verification, diagnostic, research, decision,
  report, ui.
- Mirror the user's language in title/description/acceptance (Chinese goal -> Chinese
  prose); keep code, file paths and commands in their native form.
- If the execution profile is "session_agent" you MUST return exactly ONE task covering the
  whole goal (implement and verify in a single slice).
"""

    def _user_prompt(
        self,
        goal_spec: dict,
        runtime_context: dict,
        execution_profile: str,
    ) -> str:
        workspace_files = self._workspace_file_paths(runtime_context)
        return f"""GoalSpec:
{json.dumps(goal_spec, ensure_ascii=False, indent=2)}

Execution profile: {execution_profile}
Existing workspace files:
{chr(10).join(workspace_files) if workspace_files else "(empty workspace)"}

Return this exact JSON shape:
{{
  "tasks": [
    {{
      "task_id": "task-0001",
      "title": "...",
      "description": "...",
      "task_kind": "implementation|verification|diagnostic|research|decision|report|ui",
      "priority": "critical|high|medium|low",
      "acceptance": ["observable criterion naming a file, test, or command"],
      "expected_artifacts": ["src/tool.py"],
      "expected_changed_files": ["src/tool.py"],
      "depends_on": []
    }}
  ]
}}"""

    def _workspace_file_paths(self, runtime_context: dict, cap: int = 40) -> list[str]:
        files = runtime_context.get("workspace_files", [])
        if not isinstance(files, list):
            return []
        paths: list[str] = []
        for item in files:
            if isinstance(item, dict) and item.get("path"):
                paths.append(str(item["path"]))
            elif isinstance(item, str) and item:
                paths.append(item)
        return paths[:cap]
