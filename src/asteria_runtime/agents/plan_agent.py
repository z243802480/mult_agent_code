from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace

from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.core.execution_environment import command_execution_context
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
MAX_PLAN_ATTEMPTS = 2


@dataclass
class PlanAgent:
    """L2 cognition (ADR-0033): GoalSpec -> tasks with one bounded correction.

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
        on_invalid_plan: Callable[[int, str, bool], None] | None = None,
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
        attempt = 1
        while True:
            # The original client still owns accounting and provider/budget failures.
            # Only a received but invalid plan gets format feedback, never transport errors.
            response = self.model_client.chat(request)
            try:
                return self._validated_plan(
                    response.content, goal_spec, runtime_context, execution_profile,
                )
            except PlanAgentError as exc:
                will_retry = attempt < MAX_PLAN_ATTEMPTS
                reason = str(exc)[:2000]
                if on_invalid_plan is not None:
                    on_invalid_plan(attempt, reason, will_retry)
                if not will_retry:
                    raise PlanAgentError(
                        f"task planning failed after {attempt} attempts: {exc}"
                    ) from exc
                truncated = len(response.content) > 12000
                request = replace(
                    request,
                    messages=[
                        *request.messages,
                        ChatMessage(role="assistant", content=response.content[:12000]),
                        ChatMessage(role="user", content=(
                            "The task plan failed runtime validation.\n"
                            f"Validation error: {reason}\n"
                            f"Previous response truncated: {truncated}.\n"
                            "Return a complete corrected JSON object with a non-empty tasks "
                            "array, using the original output shape. Preserve the original "
                            "GoalSpec, project guidance, acceptance and permission boundaries; "
                            "do not weaken requirements to pass validation. Do not return "
                            "patches or commentary."
                        )),
                    ],
                )
                attempt += 1

    def _validated_plan(
        self, content: str, goal_spec: dict, runtime_context: dict, execution_profile: str,
    ) -> dict:
        raw_tasks = self._parse_tasks(content)
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
        if any(not isinstance(task, dict) for task in tasks):
            raise PlanAgentError("task plan response 'tasks' must contain only task objects")
        raw_tasks = tasks
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
- Include read_scope for each task's necessary context: specifications, existing code,
  and immutable tests. A discovery task does not make its files readable to later tasks.
  Keep these read dependencies separate from expected_changed_files.
  Use exact paths from the workspace or project guidance. Do not turn guessed conventional
  paths into required evidence; discover unknown paths inside the task before relying on them.
- Give each task validation_commands that can pass after THAT task and its dependencies.
  Do not require a partial implementation to pass tests for downstream features. Keep
  tightly coupled changes together, or put complete goal verification in a final task
  depending on all implementation work. Preserve the user's full acceptance at that stage.
  Use actual available commands, never placeholders. If verification is by file evidence,
  use an empty command list. For readonly diagnostic/verification tasks, explicitly list the
  required concrete files in verification_policy.readback_paths; those files must actually be
  read. A readback proves inspection, not that an implementation defect is fixed. Keep transient
  code exploration inside the implementation task unless a separate diagnostic has a real result.
  Include required project guidance paths in read_scope as well as the files being investigated.
  For long test suites, declare a positive verification_policy.timeout_seconds based on the
  project's observed runtime. Tool timeout_seconds is available; defaults are not infinite.
- Treat unverified commands in GoalSpec as suggestions, not requirements. For document/content
  checks, specify the observable content and use file tools; only prescribe a shell command when
  it is known to be available on the host OS or in the project.
- Keep environment discovery inside the task that needs it. Do not make dependency or test-tool
  probing a separate deliverable unless the goal itself asks for an environment report. If an
  interactive check may be unavailable, state the fallback evidence honestly.
- Use concrete file paths for expected_artifacts and expected_changed_files. Never list a
  pre-existing test file the task is judged by; DO list new test files the task authors.
- expected_artifacts are mandatory outputs: the runtime checks that each listed file exists.
  An allowed edit path is permission, not a required deliverable. List intended implementation
  files in expected_changed_files within the user's scope; do not demand changes to every
  allowed file. Keep optional alternatives and conditions in description/acceptance, and only
  list an optional artifact as mandatory when this plan actually chooses and requires it.
  Path entries must be exact literal paths, with no appended explanation or condition. Preserve
  genuine Unicode and punctuation in names. Apply this distinction even when GoalSpec mixes
  allowed paths or conditional choices into target_outputs; preserve the original user contract.
- If a task may author a verification script, include that new file in the same task's
  expected_changed_files so its write scope permits creation. Keep checks near their change.
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
        guidance = runtime_context.get("root_guidance") or {}
        guidance_block = ""
        if isinstance(guidance, dict) and isinstance(guidance.get("content"), str):
            content = guidance["content"]
            if content:
                guidance_block = "\nProject guidance from the existing workspace context:\n" + json.dumps(
                    {"path": guidance.get("path"), "content": content[:4000],
                     "truncated": bool(guidance.get("truncated")) or len(content) > 4000},
                    ensure_ascii=False,
                ) + "\n"
        return f"""GoalSpec:
{json.dumps(goal_spec, ensure_ascii=False, indent=2)}
{guidance_block}

Execution profile: {execution_profile}
Execution environment: {json.dumps(command_execution_context(), ensure_ascii=False)}
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
      "read_scope": ["README.md", "src/tool.py", "tests/test_tool.py"],
      "validation_commands": ["a known available command checking this slice"],
      "verification_policy": {{"readback_paths": []}},
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
