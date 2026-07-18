from __future__ import annotations

import re

from asteria_runtime.core.execution_profile import HARNESS, SESSION_AGENT
from asteria_runtime.core.execution_preferences import apply_execution_preferences_to_task
from asteria_runtime.core.fast_path_policy import classify_risk_tier
from asteria_runtime.core.multi_agent_strategy import MultiAgentStrategyAdvisor
from asteria_runtime.core.task_contract import (
    completion_contract,
    context_requirements,
    failure_policy,
    parallel_safety,
    read_scope,
    validation_commands,
    write_scope,
)
from asteria_runtime.utils.time import now_iso


class RequirementPlanner:
    """Deterministic MVP planner that turns GoalSpec requirements into reviewable tasks."""

    def __init__(self) -> None:
        self.multi_agent_strategy = MultiAgentStrategyAdvisor()

    def build_task_plan(
        self,
        goal_spec: dict,
        runtime_context: dict | None = None,
        *,
        execution_profile: str = HARNESS,
    ) -> dict:
        runtime_context = runtime_context or {}
        if self._is_targeted_repair_goal(goal_spec):
            return {
                "schema_version": "0.1.0",
                "tasks": [self._targeted_repair_task(goal_spec, runtime_context)],
            }
        if self._is_single_file_tool(goal_spec):
            return {
                "schema_version": "0.1.0",
                "tasks": [self._single_file_task(goal_spec, runtime_context)],
            }
        if self._is_atomic_multifile_tool(goal_spec):
            return {
                "schema_version": "0.1.0",
                "tasks": [self._atomic_multifile_task(goal_spec, runtime_context)],
            }
        if execution_profile == SESSION_AGENT:
            return {
                "schema_version": "0.1.0",
                "tasks": [self._session_agent_unified_task(goal_spec, runtime_context)],
            }

        requirements: list[dict] = []
        for requirement in goal_spec["expanded_requirements"]:
            if requirement.get("priority") == "wont":
                continue
            requirement = self._refine_requirement(requirement, goal_spec)
            requirements.extend(self._split_requirement_if_needed(requirement, goal_spec))

        tasks: list[dict] = []
        for index, requirement in enumerate(requirements, start=1):
            requirement = self._attach_workspace_file_context(requirement, runtime_context)
            requirement = self._attach_existing_artifact_context(requirement, runtime_context)
            task_id = f"task-{index:04d}"
            expected_artifacts = self._expected_artifacts(requirement, goal_spec)
            kind = self._task_kind(requirement, expected_artifacts, goal_spec)
            quality = self._quality_assessment(requirement, expected_artifacts)
            task = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "title": self._title(requirement["description"]),
                "description": requirement["description"],
                "status": "ready" if not tasks else "backlog",
                "priority": self._priority(requirement["priority"]),
                "role": "CoderAgent",
                "depends_on": [] if not tasks else [tasks[-1]["task_id"]],
                "acceptance": requirement["acceptance"],
                "allowed_tools": self._allowed_tools(kind),
                "expected_artifacts": expected_artifacts,
                "task_kind": kind,
                "expected_changed_files": self._expected_changed_files(
                    kind, expected_artifacts, requirement
                ),
                "assigned_agent_id": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "quality": quality,
                "notes": self._notes(
                    requirement["id"],
                    requirement,
                    expected_artifacts,
                    runtime_context,
                    quality,
                ),
            }
            task["completion_contract"] = completion_contract(task)
            task["verification_policy"] = self._verification_policy(task, goal_spec)
            self._apply_runtime_contract(task, goal_spec)
            tasks.append(task)

        if not tasks:
            task = {
                "schema_version": "0.1.0",
                "task_id": "task-0001",
                "title": "Clarify goal and create first implementation slice",
                "description": goal_spec["normalized_goal"],
                "status": "ready",
                "priority": "high",
                "role": "PlannerAgent",
                "depends_on": [],
                "acceptance": goal_spec["definition_of_done"][:3] or ["Goal is clarified"],
                "allowed_tools": self._allowed_tools("implementation"),
                "expected_artifacts": self._fallback_artifacts(goal_spec),
                "task_kind": "implementation",
                "expected_changed_files": self._expected_changed_files(
                    "implementation", self._fallback_artifacts(goal_spec)
                ),
                "assigned_agent_id": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "quality": {
                    "clarity_score": 0.60,
                    "testability_score": 0.60,
                    "size_score": 0.70,
                    "artifact_score": 0.60,
                    "dependency_score": 0.80,
                    "risk_score": 0.70,
                    "passed": False,
                },
                "notes": (
                    "Fallback task because no actionable requirements were generated. "
                    "Quality: clarity=0.60 testability=0.60 size=0.70 artifact=0.60."
                ),
            }
            task["completion_contract"] = completion_contract(task)
            task["verification_policy"] = self._verification_policy(task, goal_spec)
            self._apply_runtime_contract(task, goal_spec)
            tasks.append(task)
        return {"schema_version": "0.1.0", "tasks": tasks}

    def _is_single_file_tool(self, goal_spec: dict) -> bool:
        text = " ".join(
            [
                str(goal_spec.get("original_goal", "")),
                str(goal_spec.get("normalized_goal", "")),
                " ".join(str(item) for item in goal_spec.get("target_outputs", [])),
                " ".join(str(item) for item in goal_spec.get("constraints", [])),
            ]
        ).lower()
        return (
            "single-file" in text
            or "single file" in text
            or self._single_output_file(goal_spec) is not None
        )

    def _single_output_file(self, goal_spec: dict) -> str | None:
        outputs = [
            str(item).strip()
            for item in goal_spec.get("target_outputs", [])
            if isinstance(item, str) and self._looks_like_file_path(str(item).strip())
        ]
        if len(outputs) == 1:
            return outputs[0]
        text = " ".join(
            [
                str(goal_spec.get("original_goal", "")),
                str(goal_spec.get("normalized_goal", "")),
                " ".join(str(item) for item in goal_spec.get("definition_of_done", [])),
            ]
        )
        matches = list(dict.fromkeys(re.findall(r"\b[\w.-]+\.[A-Za-z0-9]{1,8}\b", text)))
        return matches[0] if len(matches) == 1 else None

    def _looks_like_file_path(self, value: str) -> bool:
        if not value or value.endswith(("/", "\\")):
            return False
        name = value.replace("\\", "/").rsplit("/", 1)[-1]
        return bool(re.match(r"^[\w.-]+\.[A-Za-z0-9]{1,8}$", name))

    def _is_atomic_multifile_tool(self, goal_spec: dict) -> bool:
        text = self._goal_text(goal_spec).lower()
        explicit_files = self._explicit_goal_files(goal_spec)
        if len([item for item in explicit_files if item.endswith(".py")]) < 2:
            return False
        has_tool_shape = any(
            marker in text for marker in {" cli", "command", "entrypoint", "package"}
        )
        has_runtime_checks = bool(self._command_examples(goal_spec)) or "support `" in text
        return has_tool_shape and has_runtime_checks

    def _is_targeted_repair_goal(self, goal_spec: dict) -> bool:
        text = self._goal_text(goal_spec).lower()
        explicit_files = [
            item
            for item in self._explicit_goal_files(goal_spec)
            if not self._is_runtime_data_artifact(item)
        ]
        has_code_repair_target = any(item.endswith(".py") for item in explicit_files)
        has_repair_intent = any(
            marker in text
            for marker in {
                "fix ",
                "repair ",
                "fix the failing tests",
                "fix failing tests",
                "repair failing tests",
                "identify the bug",
                "bug in",
            }
        )
        return has_repair_intent and has_code_repair_target

    def _targeted_repair_task(self, goal_spec: dict, runtime_context: dict) -> dict:
        artifacts = [
            item
            for item in self._explicit_goal_files(goal_spec)
            if not self._is_runtime_data_artifact(item)
        ]
        acceptance = self._targeted_repair_acceptance(goal_spec, artifacts)
        requirement = {
            "id": "req-targeted-repair",
            "priority": "must",
            "description": str(
                goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or ""
            ),
            "acceptance": acceptance,
            "expected_artifacts": artifacts,
        }
        quality = self._quality_assessment(requirement, artifacts)
        expected_changed_files = self._filter_non_modified_test_paths(
            artifacts, self._targeted_repair_description(goal_spec)
        )
        task = {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Repair targeted failing behavior and verify",
            "description": self._targeted_repair_description(goal_spec),
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": acceptance,
            "allowed_tools": self._allowed_tools("implementation"),
            "expected_artifacts": artifacts,
            "task_kind": "implementation",
            "expected_changed_files": expected_changed_files,
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "quality": quality,
            "notes": (
                "Grouped into one targeted repair slice because the goal names the failing "
                "behavior and concrete file boundary. "
                + self._notes(
                    "req-targeted-repair", requirement, artifacts, runtime_context, quality
                )
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = self._verification_policy(task, goal_spec)
        self._apply_runtime_contract(task, goal_spec)
        return task

    def _targeted_repair_description(self, goal_spec: dict) -> str:
        lines = [
            str(goal_spec.get("original_goal") or goal_spec.get("normalized_goal") or "").strip()
        ]
        for requirement in goal_spec.get("expanded_requirements", [])[:8]:
            if requirement.get("priority") != "wont":
                lines.append(f"- {requirement.get('description', '')}")
        return "\n".join(line for line in lines if line.strip())

    def _targeted_repair_acceptance(self, goal_spec: dict, artifacts: list[str]) -> list[str]:
        acceptance: list[str] = []
        for item in goal_spec.get("definition_of_done", []):
            if isinstance(item, str) and item.strip():
                acceptance.append(item.strip())
        for requirement in goal_spec.get("expanded_requirements", []):
            if requirement.get("priority") == "wont":
                continue
            for item in requirement.get("acceptance", []):
                if isinstance(item, str) and item.strip():
                    acceptance.append(item.strip())
        for artifact in artifacts:
            acceptance.append(f"{artifact} is updated only as needed for the repair")
        for command in self._command_examples(goal_spec):
            acceptance.append(f"`{command}` exits successfully")
        if not self._command_examples(goal_spec):
            acceptance.append("The relevant test command passes")
        return list(dict.fromkeys(acceptance))[:12]

    def _atomic_multifile_task(self, goal_spec: dict, runtime_context: dict) -> dict:
        artifacts = self._explicit_goal_files(goal_spec)
        source_artifacts = [
            artifact for artifact in artifacts if not self._is_runtime_data_artifact(artifact)
        ]
        acceptance = self._atomic_multifile_acceptance(goal_spec, artifacts)
        description_lines = [
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "").strip()
        ]
        for requirement in goal_spec.get("expanded_requirements", [])[:12]:
            if requirement.get("priority") != "wont":
                description_lines.append(f"- {requirement.get('description', '')}")
        requirement = {
            "id": "req-atomic-multifile",
            "priority": "must",
            "description": "\n".join(line for line in description_lines if line.strip()),
            "acceptance": acceptance,
            "expected_artifacts": artifacts,
        }
        quality = self._quality_assessment(requirement, artifacts)
        task = {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Implement complete multi-file CLI artifact set",
            "description": requirement["description"],
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": acceptance,
            "allowed_tools": self._allowed_tools("implementation"),
            "expected_artifacts": artifacts,
            "task_kind": "implementation",
            "expected_changed_files": source_artifacts,
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "quality": quality,
            "notes": (
                "Grouped into one complete multi-file tool slice because the goal names a "
                "coupled artifact set that must work together. Runtime data artifacts are "
                "verified through commands, not required as source edits. "
                + self._notes(
                    "req-atomic-multifile", requirement, artifacts, runtime_context, quality
                )
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = self._verification_policy(task, goal_spec)
        self._apply_runtime_contract(task, goal_spec)
        return task

    def _atomic_multifile_acceptance(self, goal_spec: dict, artifacts: list[str]) -> list[str]:
        acceptance: list[str] = []
        for item in goal_spec.get("definition_of_done", []):
            if isinstance(item, str) and item.strip():
                acceptance.append(item.strip())
        for requirement in goal_spec.get("expanded_requirements", []):
            if requirement.get("priority") == "wont":
                continue
            for item in requirement.get("acceptance", []):
                if isinstance(item, str) and item.strip():
                    acceptance.append(item.strip())
        for command in self._command_examples(goal_spec):
            acceptance.append(f"`{command}` exits successfully")
        for artifact in artifacts:
            if self._is_runtime_data_artifact(artifact):
                acceptance.append(f"Runtime commands create or update {artifact} as specified")
            else:
                acceptance.append(f"{artifact} is created or updated")
        return list(dict.fromkeys(acceptance))[:12] or [
            "The named multi-file tool artifacts are created and verified together"
        ]

    def _explicit_goal_files(self, goal_spec: dict) -> list[str]:
        text = self._goal_text(goal_spec)
        files = self._explicit_file_paths(text)
        package_dir = self._package_dir(text)
        normalized: list[str] = []
        for file_path in files:
            path = file_path.replace("\\", "/")
            if package_dir and "/" not in path and self._looks_like_package_module(path, text):
                path = f"{package_dir}/{path}"
            normalized.append(path)
        if package_dir and any(item.startswith(f"{package_dir}/") for item in normalized):
            normalized.append(f"{package_dir}/__init__.py")
        return list(dict.fromkeys(normalized))

    def _goal_text(self, goal_spec: dict) -> str:
        return " ".join(
            [
                str(goal_spec.get("original_goal") or ""),
                str(goal_spec.get("normalized_goal") or ""),
                " ".join(str(item) for item in goal_spec.get("target_outputs", []) if item),
                " ".join(str(item) for item in goal_spec.get("constraints", []) if item),
                " ".join(str(item) for item in goal_spec.get("definition_of_done", []) if item),
                " ".join(
                    str(requirement.get("description") or "")
                    for requirement in goal_spec.get("expanded_requirements", [])
                    if isinstance(requirement, dict)
                ),
                " ".join(
                    " ".join(str(item) for item in requirement.get("acceptance", []) if item)
                    for requirement in goal_spec.get("expanded_requirements", [])
                    if isinstance(requirement, dict)
                ),
            ]
        )

    def _package_dir(self, text: str) -> str | None:
        match = re.search(
            r"\bpackage\s+directory\s+(?:named|called)\s+([A-Za-z_][\w-]*)",
            text,
            flags=re.I,
        )
        return match.group(1) if match else None

    def _looks_like_package_module(self, path: str, text: str) -> bool:
        stem = path.rsplit("/", 1)[-1]
        if stem == "__init__.py":
            return True
        if re.search(rf"\brunnable\s+{re.escape(stem)}\s+entrypoint\b", text, flags=re.I):
            return False
        return stem in {"cli.py", "storage.py", "models.py", "model.py", "core.py", "utils.py"}

    def _is_runtime_data_artifact(self, path: str) -> bool:
        return path.endswith(".json") and "/" not in path

    def _command_examples(self, goal_spec: dict) -> list[str]:
        text = self._goal_text(goal_spec)
        commands = re.findall(r"`([^`]+)`", text)
        return [
            command.strip()
            for command in commands
            if command.strip().startswith(("python ", "pytest", "ruff ", "mypy "))
        ][:5]

    def _session_agent_unified_task(self, goal_spec: dict, runtime_context: dict) -> dict:
        """One CC-like task slice: implement + verify in a single agent session."""
        artifacts = self._explicit_goal_files(goal_spec)
        source_artifacts = [
            artifact for artifact in artifacts if not self._is_runtime_data_artifact(artifact)
        ]
        requirements = [
            requirement
            for requirement in goal_spec.get("expanded_requirements", [])
            if requirement.get("priority") != "wont"
        ]
        task_kind = self._session_agent_task_kind(requirements, goal_spec)
        acceptance = self._session_agent_acceptance(goal_spec, requirements, artifacts)
        description_lines = [
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "").strip()
        ]
        for requirement in requirements[:12]:
            description_lines.append(f"- {requirement.get('description', '')}")
        requirement = {
            "id": "req-session-agent",
            "priority": "must",
            "description": "\n".join(line for line in description_lines if line.strip()),
            "acceptance": acceptance,
            "expected_artifacts": artifacts or source_artifacts or ["implementation artifact"],
        }
        quality = self._quality_assessment(
            requirement,
            requirement["expected_artifacts"],
        )
        expected_changed = self._expected_changed_files(
            task_kind,
            requirement["expected_artifacts"],
            requirement,
        ) or source_artifacts
        task = {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": self._title(requirement["description"]),
            "description": requirement["description"],
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": acceptance,
            "allowed_tools": self._allowed_tools(task_kind),
            "expected_artifacts": requirement["expected_artifacts"],
            "task_kind": task_kind,
            "expected_changed_files": expected_changed,
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "quality": quality,
            "execution_profile": SESSION_AGENT,
            "notes": (
                "Session-agent unified slice: one task loop with in-session retry; "
                "no replan lineage for Beta/single-writer work. "
                + self._notes(
                    "req-session-agent",
                    requirement,
                    requirement["expected_artifacts"],
                    runtime_context,
                    quality,
                )
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = self._verification_policy(task, goal_spec)
        self._apply_runtime_contract(task, goal_spec)
        return task

    def _session_agent_task_kind(self, requirements: list[dict], goal_spec: dict) -> str:
        for requirement in requirements:
            explicit = str(requirement.get("task_kind") or "").strip().lower()
            if explicit:
                return explicit
        description_lines = [
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "").strip()
        ]
        for requirement in requirements[:12]:
            description_lines.append(f"- {requirement.get('description', '')}")
        merged = {
            "description": "\n".join(line for line in description_lines if line.strip()),
            "acceptance": self._session_agent_acceptance(
                goal_spec,
                requirements,
                self._explicit_goal_files(goal_spec),
            ),
        }
        artifacts = self._explicit_goal_files(goal_spec) or ["implementation artifact"]
        return self._task_kind(merged, artifacts, goal_spec)

    def _session_agent_acceptance(
        self,
        goal_spec: dict,
        requirements: list[dict],
        artifacts: list[str],
    ) -> list[str]:
        acceptance: list[str] = []
        for item in goal_spec.get("definition_of_done", []):
            if isinstance(item, str) and item.strip():
                acceptance.append(item.strip())
        for requirement in requirements:
            for item in requirement.get("acceptance", []):
                if isinstance(item, str) and item.strip():
                    acceptance.append(item.strip())
        for command in self._command_examples(goal_spec):
            acceptance.append(f"`{command}` exits successfully")
        for artifact in artifacts:
            if self._is_runtime_data_artifact(artifact):
                acceptance.append(f"Runtime commands create or update {artifact} as specified")
            elif artifact not in {"implementation artifact", "planning artifact"}:
                acceptance.append(f"{artifact} is created or updated")
        return list(dict.fromkeys(acceptance))[:16] or [
            "Goal is implemented and verified in one session"
        ]

    def _single_file_task(self, goal_spec: dict, runtime_context: dict) -> dict:
        artifact = self._single_file_artifact(goal_spec)
        requirements = [
            requirement
            for requirement in goal_spec.get("expanded_requirements", [])
            if requirement.get("priority") != "wont"
        ]
        description_lines = [
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal"))
        ]
        for requirement in requirements[:12]:
            description_lines.append(f"- {requirement.get('description', '')}")
        acceptance = self._single_file_acceptance(goal_spec, requirements)
        requirement = {
            "id": "req-single-file",
            "priority": "must",
            "description": "\n".join(line for line in description_lines if line.strip()),
            "acceptance": acceptance,
            "expected_artifacts": [artifact],
        }
        quality = self._quality_assessment(requirement, [artifact])
        task = {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": f"Implement {artifact} as a complete single-file artifact",
            "description": requirement["description"],
            "status": "ready",
            "priority": "high",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": acceptance,
            "allowed_tools": self._allowed_tools("implementation"),
            "expected_artifacts": [artifact],
            "task_kind": "implementation",
            "expected_changed_files": [artifact],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "quality": quality,
            "execution_profile": SESSION_AGENT,
            "notes": (
                "Grouped into one complete single-file tool/artifact slice because the goal targets one concrete file. "
                + self._notes("req-single-file", requirement, [artifact], runtime_context, quality)
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = self._verification_policy(task, goal_spec)
        self._apply_runtime_contract(task, goal_spec)
        return task

    def _single_file_artifact(self, goal_spec: dict) -> str:
        explicit_files = self._explicit_goal_files(goal_spec)
        if len(explicit_files) == 1:
            return explicit_files[0]
        explicit = self._single_output_file(goal_spec)
        if explicit:
            return explicit
        text = " ".join(
            [
                str(goal_spec.get("original_goal", "")),
                str(goal_spec.get("normalized_goal", "")),
                " ".join(str(item) for item in goal_spec.get("target_outputs", [])),
                " ".join(str(item) for item in goal_spec.get("constraints", [])),
                " ".join(str(item) for item in goal_spec.get("definition_of_done", [])),
            ]
        )
        match = re.search(r"\b[\w.-]+\.[A-Za-z0-9]{1,8}\b", text)
        return match.group(0) if match else "tool.py"

    def _single_file_acceptance(self, goal_spec: dict, requirements: list[dict]) -> list[str]:
        acceptance: list[str] = []
        for item in goal_spec.get("definition_of_done", []):
            if isinstance(item, str) and item.strip():
                acceptance.append(item.strip())
        for requirement in requirements:
            for item in requirement.get("acceptance", []):
                if isinstance(item, str) and item.strip():
                    acceptance.append(item.strip())
        deduped = list(dict.fromkeys(acceptance))
        return deduped[:12] or ["Single-file tool exists and can be executed"]

    def _priority(self, value: str) -> str:
        return {
            "must": "high",
            "should": "medium",
            "could": "low",
            "wont": "low",
        }[value]

    def _title(self, description: str) -> str:
        trimmed = description.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."

    def _expected_artifacts(self, requirement: dict, goal_spec: dict) -> list[str]:
        explicit = requirement.get("expected_artifacts")
        if isinstance(explicit, list) and explicit:
            return [str(item) for item in explicit]
        existing = requirement.get("context_existing_artifacts")
        if isinstance(existing, list) and existing:
            return [str(item) for item in existing]
        description = str(requirement.get("description", "")).lower()
        explicit_paths = self._explicit_file_paths(self._requirement_text(requirement))
        target_outputs_raw = [str(item).strip() for item in goal_spec.get("target_outputs", [])]
        target_outputs = {item.lower() for item in target_outputs_raw}
        artifacts: list[str] = []
        artifacts.extend(explicit_paths)
        artifacts.extend(
            item.replace("\\", "/")
            for item in target_outputs_raw
            if self._looks_like_artifact_output(item)
            and item.replace("\\", "/") not in explicit_paths
        )
        if (
            ("readme" in target_outputs or "doc" in description or "documentation" in description)
            and not any(path.lower().endswith("readme.md") for path in artifacts)
        ):
            artifacts.append("README.md")
        if "test" in description or "unit_tests" in goal_spec.get("verification_strategy", []):
            artifacts.append("tests/")
        if any(output in target_outputs for output in ["local_cli", "cli", "python_module"]):
            artifacts.append("src/")
        if any(output in target_outputs for output in ["report", "markdown_report"]):
            artifacts.append("report.md")
        if not artifacts:
            artifacts.append("implementation artifact")
        return list(dict.fromkeys(artifacts))

    def _looks_like_artifact_output(self, value: str) -> bool:
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            return False
        if normalized.endswith("/"):
            return True
        return self._looks_like_file_path(normalized)

    def _fallback_artifacts(self, goal_spec: dict) -> list[str]:
        outputs = [str(item) for item in goal_spec.get("target_outputs", [])]
        return outputs or ["planning artifact"]

    def _task_kind(self, requirement: dict, expected_artifacts: list[str], goal_spec: dict) -> str:
        explicit = str(requirement.get("task_kind") or "").strip().lower()
        if explicit:
            return explicit
        text = " ".join(
            [
                str(requirement.get("description", "")),
                " ".join(str(item) for item in requirement.get("acceptance", []) if item),
            ]
        ).lower()
        description = str(requirement.get("description", "")).lower()
        if any(
            marker in text
            for marker in {
                "add ",
                "create ",
                "implement",
                "update ",
                "modify ",
                "write ",
                "补",
                "增加",
                "写一个",
                "编写",
            }
        ):
            return "implementation"
        if any(
            marker in text
            for marker in {"diagnose", "identify failing", "failing tests", "run pytest"}
        ):
            return "diagnostic"
        if any(marker in description for marker in {"verify", "verification"}):
            return "verification"
        if any(marker in text for marker in {"report", "readme", "documentation"}):
            return "report"
        if any(marker in text for marker in {"ui", "web page", "interface", "dashboard"}):
            return "ui"
        if any(marker in text for marker in {"research", "investigate"}):
            return "research"
        return "implementation"

    def _expected_changed_files(
        self,
        kind: str,
        expected_artifacts: list[str],
        requirement: dict | None = None,
    ) -> list[str]:
        requirement = requirement or {}
        concrete_outputs = [
            artifact
            for artifact in expected_artifacts
            if self._looks_like_artifact_output(artifact)
            and artifact
            not in {
                "src/",
                "tests/",
                "README.md",
                "report.md",
                "implementation artifact",
                "planning artifact",
            }
        ]
        concrete_outputs = self._filter_non_modified_test_paths(
            concrete_outputs, self._requirement_text(requirement)
        )
        if kind in {"implementation", "report", "ui"} and concrete_outputs:
            return concrete_outputs
        inferred = self._infer_changed_files_from_requirement(kind, expected_artifacts, requirement)
        if inferred:
            return inferred
        if (
            kind in {"implementation", "report", "ui"}
            and isinstance(requirement.get("expected_artifacts"), list)
            and not requirement.get("expected_artifacts_inferred")
        ):
            broad = {"implementation artifact", "planning artifact", "tests/", "src/"}
            return [artifact for artifact in expected_artifacts if artifact not in broad]
        return expected_changed_files(kind, expected_artifacts)

    def _infer_changed_files_from_requirement(
        self,
        kind: str,
        expected_artifacts: list[str],
        requirement: dict,
    ) -> list[str]:
        if kind not in {"implementation", "report", "ui"}:
            return []
        text = self._requirement_text(requirement)
        explicit_paths = self._explicit_file_paths(text)
        if explicit_paths and not self._is_existing_artifact_update(requirement):
            context_inputs = {
                str(path).replace("\\", "/").lower()
                for path in requirement.get("context_workspace_paths", [])
                if path
            }
            explicit_paths = [
                path for path in explicit_paths if path.lower() not in context_inputs
            ]
        explicit_paths = self._filter_non_modified_test_paths(explicit_paths, text)
        if explicit_paths:
            return explicit_paths

        artifacts = set(expected_artifacts)
        inferred: list[str] = []
        module_stem = self._module_stem(text)
        if module_stem == "complete_module":
            inferred.append("complete_module.py")
        elif "src/" in artifacts and module_stem:
            inferred.append(f"src/{module_stem}.py")
        if "tests/" in artifacts and module_stem:
            inferred.append(f"tests/test_{module_stem}.py")
        if "README.md" in artifacts:
            inferred.append("README.md")
        if "report.md" in artifacts:
            inferred.append("report.md")
        return list(dict.fromkeys(inferred))

    def _requirement_text(self, requirement: dict) -> str:
        return " ".join(
            [
                str(requirement.get("description") or ""),
                " ".join(str(item) for item in requirement.get("acceptance", []) if item),
            ]
        )

    def _explicit_file_paths(self, text: str) -> list[str]:
        matches = re.findall(
            r"(?<![\w.-])[\w./-]+\.(?:py|md|txt|json|html|css|js|ts|tsx|toml|yaml|yml)(?![\w.-])",
            text,
            flags=re.I,
        )
        normalized = [match.replace("\\", "/") for match in matches]
        lowered = text.lower()
        if "readme.md" in {path.lower() for path in normalized} and re.search(
            r"(?:in|under|inside)\s+(?:the\s+)?docs/?\s+directory", lowered
        ):
            normalized = [
                "docs/README.md" if path.lower() == "readme.md" else path
                for path in normalized
            ]
        return list(dict.fromkeys(normalized))

    def _module_stem(self, text: str) -> str | None:
        normalized = text.lower()
        if "notes" in normalized or "note" in normalized:
            return "notes_tool"
        if "markdown" in normalized and ("knowledge base" in normalized or "search" in normalized):
            return "markdown_kb"
        if "password strength" in normalized:
            return "password_strength"
        dotted_module = re.search(r"\b([a-z][a-z0-9_]*)\.[a-z_][a-z0-9_]*\b", normalized)
        if dotted_module:
            return dotted_module.group(1)
        if "answer()" in normalized or "answer function" in normalized:
            return "complete_module"
        candidates = re.findall(
            r"(?:create|add|implement|build|write|update)\s+(?:a|an|the)?\s*([a-z][a-z0-9_-]+)",
            normalized,
        )
        stopwords = {
            "local",
            "small",
            "simple",
            "tiny",
            "command",
            "cli",
            "module",
            "tool",
            "file",
            "test",
            "unit",
            "source",
        }
        for candidate in candidates:
            candidate = candidate.strip("_-")
            if candidate and candidate not in stopwords:
                return re.sub(r"[^a-z0-9_]+", "_", candidate)
        return None

    def _filter_non_modified_test_paths(self, paths: list[str], text: str) -> list[str]:
        lowered = text.lower()
        non_test_paths = [path for path in paths if not self._is_test_path(path)]
        if len(non_test_paths) == 1 and len(paths) > 1:
            only_target = non_test_paths[0].lower()
            if (
                f"only {only_target}" in lowered
                or f"limited to {only_target}" in lowered
                or "no other files were modified" in lowered
                or "no other files are modified" in lowered
                or "no other lines or files are modified" in lowered
            ):
                return non_test_paths
        if not any(
            marker in lowered
            for marker in {
                "no test files were modified",
                "no test files are modified",
                "no test files should be modified",
                "without modifying test files",
            }
        ):
            return paths
        return [
            path
            for path in paths
            if not self._is_test_path(path)
        ]

    def _is_test_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        return (
            normalized.split("/")[-1].startswith("test_")
            or "/test_" in normalized
            or normalized.startswith("tests/")
        )

    def _allowed_tools(self, kind: str) -> list[str]:
        # find_files (glob) and todo_read are read-only and belong wherever the other read tools
        # are granted; todo_write mutates only run-local planning state (not workspace files) so it
        # rides with the implementation/report tool sets. All four are already advertised on the
        # agent tool surface — including them here closes the "advertised but contract-denied" gap.
        # remember/recall_memory mutate only append-only agent memory under .asteria/memory
        # (never workspace files), and the lessons most worth keeping — a failed approach, a
        # repo quirk, a research claim — surface during diagnostic/research tasks as much as
        # during implementation, so both ride every task kind including the readonly set.
        readonly = [
            "list_files",
            "read_file",
            "search_text",
            "find_files",
            "todo_read",
            "remember",
            "recall_memory",
            "run_command",
            "run_tests",
        ]
        if kind in {"diagnostic", "verification", "research", "decision"}:
            return readonly
        if kind == "report":
            return [
                "list_files",
                "read_file",
                "search_text",
                "find_files",
                "diff_workspace",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "todo_read",
                "todo_write",
                "remember",
                "recall_memory",
            ]
        return [
            "list_files",
            "read_file",
            "search_text",
            "find_files",
            "diff_workspace",
            "write_file",
            "apply_patch",
            "restore_backup",
            "run_command",
            "run_tests",
            "todo_read",
            "todo_write",
            "remember",
            "recall_memory",
        ]

    def _verification_policy(self, task: dict, goal_spec: dict) -> dict:
        contract = completion_contract(task)
        commands = [
            str(item)
            for item in goal_spec.get("verification_strategy", [])
            if isinstance(item, str) and item.strip()
        ]
        return {
            "required": bool(contract.get("requires_verification", False)),
            "allow_expected_failure": bool(contract.get("allows_expected_failure", False)),
            "commands": commands[:5],
        }

    def _apply_runtime_contract(self, task: dict, goal_spec: dict | None = None) -> None:
        task["read_scope"] = read_scope(task)
        apply_execution_preferences_to_task(task, goal_spec)
        task["read_scope"] = read_scope(task)
        task["write_scope"] = write_scope(task)
        task["context_requirements"] = context_requirements(task)
        task["validation_commands"] = validation_commands(task)
        task["failure_policy"] = failure_policy(task)
        task["parallel_safety"] = parallel_safety(task)
        task["risk_tier"] = classify_risk_tier(
            str(task.get("title") or task.get("description") or ""),
            task=task,
        ).risk_tier
        task["merge_strategy"] = "none"
        self._harden_broad_write_scope(task)
        self._mark_disjoint_write_scope(task)
        strategy = self.multi_agent_strategy.for_task(task).to_dict()
        task["multi_agent_strategy"] = strategy
        task["notes"] = (
            f"{task.get('notes', '')} Multi-agent strategy: {strategy['mode']} "
            f"(max_child_workers={strategy['max_child_workers']}; {strategy['reason']})."
        ).strip()

    def _harden_broad_write_scope(self, task: dict) -> None:
        broad = {"src/", "tests/", "docs/", "docs/zh/"}
        scope = [str(item) for item in task.get("write_scope", []) if item]
        if not scope or any(item not in broad for item in scope):
            return
        if task.get("expected_changed_files"):
            return
        task["write_scope"] = []
        task["parallel_safety"] = "serial"
        task["notes"] = (
            f"{task.get('notes', '')} Scope quality: write_scope was broad "
            f"({', '.join(scope)}), so it was narrowed to require a runtime scope request."
        ).strip()

    def _mark_disjoint_write_scope(self, task: dict) -> None:
        scope = [str(item) for item in task.get("write_scope", []) if item]
        if len(scope) <= 1 or task.get("parallel_safety") != "serial":
            return
        if any(item.startswith("src/") for item in scope) and any(
            item.startswith("tests/") for item in scope
        ):
            return
        if all(self._looks_like_file_path(item) for item in scope) and len(set(scope)) == len(scope):
            task["parallel_safety"] = "disjoint_writes"

    def _attach_workspace_file_context(self, requirement: dict, runtime_context: dict) -> dict:
        paths = self._existing_workspace_paths(runtime_context)
        if not paths:
            return requirement
        refined = dict(requirement)
        refined["context_workspace_paths"] = paths
        return refined

    def _attach_existing_artifact_context(
        self, requirement: dict, runtime_context: dict
    ) -> dict:
        if isinstance(requirement.get("expected_artifacts"), list) and requirement.get(
            "expected_artifacts"
        ):
            return requirement
        if not self._is_existing_artifact_update(requirement):
            return requirement
        paths = self._existing_workspace_paths(runtime_context)
        if not paths:
            return requirement
        matches = self._matching_existing_paths(requirement, paths)
        if not matches:
            return requirement
        refined = dict(requirement)
        refined["context_existing_artifacts"] = matches
        return refined

    def _is_existing_artifact_update(self, requirement: dict) -> bool:
        text = self._requirement_text(requirement).lower()
        update_markers = {
            "update",
            "modify",
            "edit",
            "fix",
            "repair",
            "improve",
            "extend",
            "refactor",
        }
        create_markers = {"create", "build", "generate", "write a new", "add a new"}
        if not any(self._contains_phrase(text, marker) for marker in update_markers):
            return False
        if any(self._contains_phrase(text, marker) for marker in create_markers) and (
            not self._contains_phrase(text, "existing")
        ):
            return False
        return True

    def _contains_phrase(self, text: str, phrase: str) -> bool:
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text) is not None

    def _existing_workspace_paths(self, runtime_context: dict) -> list[str]:
        paths: list[str] = []
        workspace_files = runtime_context.get("workspace_files", [])
        if isinstance(workspace_files, list):
            for item in workspace_files:
                if isinstance(item, dict) and item.get("path"):
                    paths.append(str(item["path"]))
        for key in ("latest_handoff", "latest_snapshot"):
            value = runtime_context.get(key)
            if not isinstance(value, dict):
                continue
            for collection_key in ("recent_artifacts", "modified_files"):
                collection = value.get(collection_key)
                if not isinstance(collection, list):
                    continue
                for item in collection:
                    if isinstance(item, str):
                        paths.append(item)
                    elif isinstance(item, dict):
                        path = item.get("path") or item.get("file") or item.get("artifact")
                        if path:
                            paths.append(str(path))
        return [
            path
            for path in dict.fromkeys(item.replace("\\", "/").strip() for item in paths if item)
            if self._looks_like_file_path(path) and not path.startswith(".asteria/")
        ]

    def _matching_existing_paths(self, requirement: dict, paths: list[str]) -> list[str]:
        text = self._requirement_text(requirement).lower()
        explicit = set(self._explicit_file_paths(text))
        matches = [path for path in paths if path.lower() in explicit]
        if matches:
            return matches

        text_tokens = set(re.findall(r"[a-z0-9_]+", text))
        selected: list[str] = []
        for path in paths:
            basename = path.rsplit("/", 1)[-1]
            stem = basename.rsplit(".", 1)[0].lower()
            candidates = {stem, stem.replace("_", "-")}
            if stem.startswith("test_"):
                candidates.add(stem[5:])
            if stem.endswith("_test"):
                candidates.add(stem[:-5])
            split_tokens = {token for token in re.split(r"[_-]+", stem) if token}
            if (
                stem in text
                or candidates & text_tokens
                or (split_tokens and split_tokens <= text_tokens)
            ):
                selected.append(path)
        return selected[:6]

    def _refine_requirement(self, requirement: dict, goal_spec: dict) -> dict:
        expected_artifacts = self._expected_artifacts(requirement, goal_spec)
        quality = self._quality_assessment(requirement, expected_artifacts)
        if quality["passed"]:
            return requirement

        refined = dict(requirement)
        description = str(refined.get("description", "")).strip()
        if quality["clarity_score"] < 0.75:
            normalized_goal = str(goal_spec.get("normalized_goal", "the requested goal")).strip()
            refined["description"] = (
                f"Implement a verifiable slice for '{normalized_goal}': {description or 'initial work'}"
            )
        acceptance = refined.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance:
            artifacts = self._expected_artifacts(refined, goal_spec)
            refined["acceptance"] = [
                f"{artifact} is created or updated" for artifact in artifacts[:3]
            ] or ["The task produces a verifiable artifact"]
        if (
            not isinstance(refined.get("expected_artifacts"), list)
            or not refined["expected_artifacts"]
        ):
            refined["expected_artifacts"] = self._expected_artifacts(refined, goal_spec)
            refined["expected_artifacts_inferred"] = True
        refined["quality_refined"] = True
        return refined

    def _split_requirement_if_needed(self, requirement: dict, goal_spec: dict) -> list[dict]:
        acceptance = [
            str(item).strip()
            for item in requirement.get("acceptance", [])
            if isinstance(item, str) and item.strip()
        ]
        explicit_artifacts = [
            str(item).strip()
            for item in requirement.get("expected_artifacts", [])
            if isinstance(item, str) and item.strip()
        ]
        if len(acceptance) <= 4 and len(explicit_artifacts) <= 3:
            return [requirement]
        if explicit_artifacts and len(explicit_artifacts) > 3:
            return self._split_by_artifact(requirement, explicit_artifacts, acceptance)
        return self._split_by_acceptance(requirement, acceptance, goal_spec)

    def _split_by_artifact(
        self,
        requirement: dict,
        artifacts: list[str],
        acceptance: list[str],
    ) -> list[dict]:
        split: list[dict] = []
        for index, artifact in enumerate(artifacts, start=1):
            item = dict(requirement)
            item["id"] = f"{requirement.get('id', 'req')}.slice-{index:02d}"
            item["description"] = f"{requirement.get('description', '').strip()} [{artifact}]"
            item["acceptance"] = (
                [acceptance[index - 1]]
                if index <= len(acceptance)
                else [f"{artifact} is created or updated"]
            )
            item["expected_artifacts"] = [artifact]
            item["split_from"] = requirement.get("id")
            item["granularity_refined"] = True
            split.append(item)
        return split

    def _split_by_acceptance(
        self,
        requirement: dict,
        acceptance: list[str],
        goal_spec: dict,
    ) -> list[dict]:
        chunks = [acceptance[index : index + 3] for index in range(0, len(acceptance), 3)]
        artifacts = self._expected_artifacts(requirement, goal_spec)
        split: list[dict] = []
        for index, chunk in enumerate(chunks, start=1):
            item = dict(requirement)
            item["id"] = f"{requirement.get('id', 'req')}.slice-{index:02d}"
            item["description"] = (
                f"{requirement.get('description', '').strip()} "
                f"(acceptance slice {index}/{len(chunks)})"
            )
            item["acceptance"] = chunk
            item["expected_artifacts"] = artifacts
            item["split_from"] = requirement.get("id")
            item["granularity_refined"] = True
            split.append(item)
        return split

    def _notes(
        self,
        requirement_id: str,
        requirement: dict,
        expected_artifacts: list[str],
        runtime_context: dict,
        quality: dict,
    ) -> str:
        context_note = self._context_note(runtime_context)
        refinement_note = " Refined for task quality." if requirement.get("quality_refined") else ""
        granularity_note = (
            f" Split from {requirement.get('split_from')} for task granularity."
            if requirement.get("granularity_refined")
            else ""
        )
        return (
            f"Generated from {requirement_id}. "
            "Quality: "
            f"clarity={quality['clarity_score']:.2f} "
            f"testability={quality['testability_score']:.2f} "
            f"size={quality['size_score']:.2f} "
            f"artifact={quality['artifact_score']:.2f}."
            f"{refinement_note}"
            f"{granularity_note}"
            f"{context_note}"
        )

    def _quality_assessment(self, requirement: dict, expected_artifacts: list[str]) -> dict:
        description = str(requirement.get("description", "")).strip()
        acceptance = requirement.get("acceptance", [])
        acceptance_count = len(acceptance) if isinstance(acceptance, list) else 0
        max_acceptance = 12 if requirement.get("id") == "req-single-file" else 4
        scores = {
            "clarity_score": 0.85 if len(description.split()) >= 4 else 0.65,
            "testability_score": 0.85 if acceptance_count >= 1 else 0.55,
            "size_score": 0.80 if 1 <= acceptance_count <= max_acceptance else 0.65,
            "artifact_score": 0.85 if expected_artifacts else 0.50,
            "dependency_score": 0.80,
            "risk_score": 0.75,
        }
        scores["passed"] = (
            scores["clarity_score"] >= 0.75
            and scores["testability_score"] >= 0.75
            and scores["size_score"] >= 0.70
            and scores["artifact_score"] >= 0.75
        )
        return scores

    def _context_note(self, runtime_context: dict) -> str:
        memory_count = len(runtime_context.get("memory", []))
        snapshot_id = runtime_context.get("latest_snapshot", {}).get("snapshot_id")
        handoff_id = runtime_context.get("latest_handoff", {}).get("handoff_id")
        capability_feedback = runtime_context.get("capability_feedback", [])
        parts = []
        if memory_count:
            parts.append(f"{memory_count} memory entr{'y' if memory_count == 1 else 'ies'}")
        if snapshot_id:
            parts.append(f"snapshot {snapshot_id}")
        if handoff_id:
            parts.append(f"handoff {handoff_id}")
        if isinstance(capability_feedback, list) and capability_feedback:
            hint = capability_feedback[0]
            if isinstance(hint, dict) and hint.get("message"):
                parts.append(f"capability feedback: {hint['message']}")
        return f" Context: {', '.join(parts)}." if parts else ""


def expected_changed_files(kind: str, expected_artifacts: list[str]) -> list[str]:
    if kind not in {"implementation", "report", "ui"}:
        return []
    generic = {
        "implementation artifact",
        "planning artifact",
        "tests/",
        "src/",
        "README.md",
        "report.md",
    }
    return [artifact for artifact in expected_artifacts if artifact not in generic]
