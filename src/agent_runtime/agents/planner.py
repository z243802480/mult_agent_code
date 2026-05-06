from __future__ import annotations

import re

from agent_runtime.core.task_contract import completion_contract
from agent_runtime.utils.time import now_iso


class RequirementPlanner:
    """Deterministic MVP planner that turns GoalSpec requirements into reviewable tasks."""

    def build_task_plan(self, goal_spec: dict, runtime_context: dict | None = None) -> dict:
        runtime_context = runtime_context or {}
        if self._is_single_file_tool(goal_spec):
            return {
                "schema_version": "0.1.0",
                "tasks": [self._single_file_task(goal_spec, runtime_context)],
            }

        requirements: list[dict] = []
        for requirement in goal_spec["expanded_requirements"]:
            if requirement.get("priority") == "wont":
                continue
            requirement = self._refine_requirement(requirement, goal_spec)
            requirements.extend(self._split_requirement_if_needed(requirement, goal_spec))

        tasks: list[dict] = []
        for index, requirement in enumerate(requirements, start=1):
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
                "allowed_tools": [
                    "read_file",
                    "search_text",
                    "write_file",
                    "apply_patch",
                    "restore_backup",
                    "run_command",
                    "run_tests",
                ],
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
                "allowed_tools": ["read_file", "search_text", "write_file"],
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
            "allowed_tools": [
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "run_tests",
            ],
            "expected_artifacts": [artifact],
            "task_kind": "implementation",
            "expected_changed_files": [artifact],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "quality": quality,
            "notes": (
                "Grouped into one complete single-file tool/artifact slice because the goal targets one concrete file. "
                + self._notes("req-single-file", requirement, [artifact], runtime_context, quality)
            ),
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = self._verification_policy(task, goal_spec)
        return task

    def _single_file_artifact(self, goal_spec: dict) -> str:
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
        description = str(requirement.get("description", "")).lower()
        target_outputs = {str(item).lower() for item in goal_spec.get("target_outputs", [])}
        artifacts: list[str] = []
        if "readme" in target_outputs or "doc" in description or "documentation" in description:
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
            for marker in {"diagnose", "identify failing", "failing tests", "run pytest"}
        ):
            return "diagnostic"
        if any(marker in description for marker in {"verify", "verification"}):
            return "verification"
        if any(marker in text for marker in {"report", "readme", "documentation"}):
            return "report"
        if any(marker in text for marker in {"ui", "web page", "interface", "dashboard"}):
            return "ui"
        if any(marker in text for marker in {"research", "investigate", "source"}):
            return "research"
        return "implementation"

    def _expected_changed_files(
        self,
        kind: str,
        expected_artifacts: list[str],
        requirement: dict | None = None,
    ) -> list[str]:
        requirement = requirement or {}
        if (
            kind in {"implementation", "report", "ui"}
            and isinstance(requirement.get("expected_artifacts"), list)
            and not requirement.get("expected_artifacts_inferred")
        ):
            broad = {"implementation artifact", "planning artifact", "tests/", "src/"}
            return [artifact for artifact in expected_artifacts if artifact not in broad]
        return expected_changed_files(kind, expected_artifacts)

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
        parts = []
        if memory_count:
            parts.append(f"{memory_count} memory entr{'y' if memory_count == 1 else 'ies'}")
        if snapshot_id:
            parts.append(f"snapshot {snapshot_id}")
        if handoff_id:
            parts.append(f"handoff {handoff_id}")
        return f" Context: {', '.join(parts)}." if parts else ""


class FollowUpTaskPlanner:
    def build_follow_up_tasks(self, eval_report: dict, existing_tasks: list[dict]) -> list[dict]:
        follow_ups = eval_report.get("outcome_eval", {}).get("follow_up_tasks", [])
        if not follow_ups:
            follow_ups = eval_report.get("trajectory_eval", {}).get("follow_up_tasks", [])
        if not isinstance(follow_ups, list):
            return []

        next_index = self._next_index(existing_tasks)
        done_or_ready = [
            task["task_id"] for task in existing_tasks if task["status"] != "discarded"
        ]
        known_items = {self._normalize(task.get("title", "")) for task in existing_tasks} | {
            self._normalize(task.get("description", "")) for task in existing_tasks
        }
        dependency = done_or_ready[-1:] if done_or_ready else []
        tasks: list[dict] = []
        for item in follow_ups:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or item.get("title") or "").strip()
            if not description:
                continue
            title = self._title(str(item.get("title") or description))
            if self._normalize(title) in known_items or self._normalize(description) in known_items:
                continue
            task_id = f"task-{next_index:04d}"
            next_index += 1
            acceptance = item.get("acceptance")
            expected_artifacts = item.get("expected_artifacts")
            if not isinstance(acceptance, list) or not acceptance:
                acceptance = ["Follow-up requirement is implemented and verified"]
            if not isinstance(expected_artifacts, list):
                expected_artifacts = []
            kind = str(item.get("task_kind") or "implementation")
            task: dict = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "title": title,
                "description": description,
                "status": "ready" if not dependency and not tasks else "backlog",
                "priority": self._priority(str(item.get("priority") or "medium")),
                "role": str(item.get("role") or "CoderAgent"),
                "depends_on": dependency if not tasks else [tasks[-1]["task_id"]],
                "acceptance": [str(value) for value in acceptance],
                "allowed_tools": [
                    "read_file",
                    "search_text",
                    "write_file",
                    "apply_patch",
                    "restore_backup",
                    "run_command",
                    "run_tests",
                ],
                "expected_artifacts": expected_artifacts,
                "task_kind": kind,
                "expected_changed_files": expected_changed_files(kind, expected_artifacts),
                "assigned_agent_id": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "notes": f"Generated from review follow-up for {eval_report.get('run_id')}",
            }
            task["completion_contract"] = completion_contract(task)
            task["verification_policy"] = {
                "required": bool(task["completion_contract"].get("requires_verification", False)),
                "allow_expected_failure": bool(
                    task["completion_contract"].get("allows_expected_failure", False)
                ),
                "commands": [],
            }
            tasks.append(task)
            known_items.add(self._normalize(title))
            known_items.add(self._normalize(description))
        return tasks

    def _next_index(self, tasks: list[dict]) -> int:
        indexes = []
        for task in tasks:
            suffix = task["task_id"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return (max(indexes) + 1) if indexes else 1

    def _priority(self, value: str) -> str:
        return value if value in {"critical", "high", "medium", "low"} else "medium"

    def _title(self, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."

    def _normalize(self, value: object) -> str:
        return " ".join(str(value).strip().lower().split())


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
