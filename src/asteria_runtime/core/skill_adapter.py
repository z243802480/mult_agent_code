from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from asteria_runtime.core.budget import BudgetExceededError
from asteria_runtime.core.capability_decision_recorder import CapabilityDecisionRecorder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


class SkillHandler(Protocol):
    def invoke(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    scope: str = "workspace"


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    path: Path
    description: str
    scope: str = "workspace"
    parameter_contract: dict[str, Any] = field(default_factory=dict)
    artifact_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "scope": self.scope,
            "parameter_contract": self.parameter_contract,
            "artifact_types": self.artifact_types,
        }


class SkillDiscovery:
    """Discover local SKILL.md definitions without invoking their runtime behavior."""

    def __init__(self, roots: list[Path | SkillRoot]) -> None:
        self.roots = [
            root if isinstance(root, SkillRoot) else SkillRoot(path=root) for root in roots
        ]

    @classmethod
    def from_scopes(
        cls,
        *,
        global_roots: list[Path] | None = None,
        workspace_roots: list[Path] | None = None,
    ) -> SkillDiscovery:
        return cls(
            [
                *[SkillRoot(path=path, scope="global") for path in global_roots or []],
                *[SkillRoot(path=path, scope="workspace") for path in workspace_roots or []],
            ]
        )

    def discover(self) -> list[SkillDefinition]:
        definitions_by_name: dict[str, SkillDefinition] = {}
        for root in self.roots:
            if root.path.is_file() and root.path.name == "SKILL.md":
                parsed = self._parse_skill(root.path, root.scope)
                if parsed is not None:
                    definitions_by_name[parsed.name] = _prefer_skill(
                        definitions_by_name.get(parsed.name), parsed
                    )
                continue
            if not root.path.exists():
                continue
            for path in root.path.rglob("SKILL.md"):
                parsed = self._parse_skill(path, root.scope)
                if parsed is not None:
                    definitions_by_name[parsed.name] = _prefer_skill(
                        definitions_by_name.get(parsed.name), parsed
                    )
        return sorted(
            definitions_by_name.values(),
            key=lambda item: (_scope_rank(item.scope), item.name),
        )

    def _parse_skill(self, path: Path, scope: str) -> SkillDefinition | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        name = _metadata_value(text, "name") or path.parent.name
        description = _metadata_value(text, "description") or _first_paragraph(text)
        return SkillDefinition(
            name=name.strip(),
            path=path,
            description=description.strip(),
            scope=scope,
            parameter_contract=_parameter_contract(text),
            artifact_types=_artifact_types(text),
        )


class SkillManifestHandler:
    """A minimal handler for discovery-only skills that returns SKILL.md metadata."""

    def __init__(self, definition: SkillDefinition) -> None:
        self.definition = definition

    def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": f"Loaded skill definition: {self.definition.name}",
            "data": {
                "skill_definition": self.definition.to_dict(),
                "arguments": request.get("arguments") or {},
            },
            "artifacts": [],
            "status": "success",
        }


class SkillBodyHandler:
    """Production skill handler: loads the full SKILL.md *procedure*, not just its frontmatter.

    A skill is instruction/context (matching Claude Code / OpenCode skills): invoking it returns
    the full SKILL.md body plus a manifest of bundled sibling files, so the model can follow the
    procedure using its existing read/write/test/shell tools. This is the honest "skills execute"
    — a real step up from SkillManifestHandler, which only echoes name/description.
    """

    def __init__(self, definition: SkillDefinition) -> None:
        self.definition = definition

    def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        body, files = _load_skill_body_and_manifest(self.definition.path)
        return {
            "ok": True,
            "summary": f"Loaded skill procedure: {self.definition.name}",
            "data": {
                "skill_definition": self.definition.to_dict(),
                "instructions": body,
                "bundled_files": files,
                "arguments": request.get("arguments") or {},
            },
            "artifacts": [],
            "status": "success",
        }


@dataclass(frozen=True)
class SkillArtifact:
    path: str
    type: str = "artifact"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "type": self.type, "summary": self.summary}


@dataclass(frozen=True)
class SkillInvocationResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[SkillArtifact] = field(default_factory=list)
    error: str | None = None
    status: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "error": self.error,
            "status": self.status,
        }


class SkillAdapter:
    """Workflow/artifact skill adapter; not a local ToolExecutionGateway wrapper."""

    def __init__(
        self,
        handlers: dict[str, SkillHandler],
        *,
        actor: str = "SkillAdapter",
    ) -> None:
        self.handlers = handlers
        self.actor = actor

    @classmethod
    def from_skill_roots(
        cls,
        roots: list[Path | SkillRoot],
        *,
        actor: str = "SkillAdapter",
        handler: str = "manifest",
    ) -> SkillAdapter:
        """Build an adapter from skill roots.

        handler="manifest" (default) keeps the discovery-only SkillManifestHandler (back-compat);
        handler="body" uses SkillBodyHandler, which loads the full SKILL.md procedure — this is
        what the live run path uses to actually execute skills.
        """
        definitions = SkillDiscovery(roots).discover()
        handler_cls = SkillBodyHandler if handler == "body" else SkillManifestHandler
        return cls(
            {definition.name: handler_cls(definition) for definition in definitions},
            actor=actor,
        )

    def discover_skills(self) -> list[dict[str, Any]]:
        """Skills as model-facing entries named ``skill__<name>`` for the tool surface."""
        items: list[dict[str, Any]] = []
        for name, handler in sorted(self.handlers.items()):
            definition = getattr(handler, "definition", None)
            description = definition.description if isinstance(definition, SkillDefinition) else ""
            contract = (
                definition.parameter_contract if isinstance(definition, SkillDefinition) else {}
            )
            items.append(
                {
                    "name": name,
                    "model_name": f"skill__{name}",
                    "description": description,
                    "parameter_contract": contract,
                }
            )
        return items

    def catalog(self) -> list[dict[str, Any]]:
        items = []
        for name, handler in sorted(self.handlers.items()):
            definition = getattr(handler, "definition", None)
            if isinstance(definition, SkillDefinition):
                items.append(definition.to_dict())
            else:
                items.append(
                    {
                        "name": name,
                        "path": None,
                        "description": "runtime-configured skill handler",
                        "parameter_contract": {},
                        "artifact_types": [],
                    }
                )
        return items

    def invoke(
        self,
        *,
        context: RuntimeContext,
        task: dict[str, Any],
        skill_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> SkillInvocationResult:
        invocation_id = self._next_invocation_id(context)
        decision = CapabilityDecisionRecorder(self.actor).decide_skill(
            skill_name,
            task=task,
            context=context,
            skill_invocation_id=invocation_id,
        )
        args = arguments or {}
        if decision["decision"] == "deny":
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill denied: {skill_name}",
                error=decision["reason"],
                status="denied",
            )
            self._record_invocation(
                context, task, invocation_id, skill_name, args, decision, result
            )
            return result
        if context.budget:
            try:
                context.budget.record_tool_call(f"skill.{skill_name}")
            except BudgetExceededError as exc:
                result = SkillInvocationResult(
                    ok=False,
                    summary=f"Skill denied by budget: {skill_name}",
                    error=str(exc),
                    status="denied",
                )
                self._record_invocation(
                    context, task, invocation_id, skill_name, args, decision, result
                )
                return result
        handler = self.handlers.get(skill_name)
        if handler is None:
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill handler not configured: {skill_name}",
                error="skill_handler_not_configured",
                status="config_error",
            )
            self._record_invocation(
                context, task, invocation_id, skill_name, args, decision, result
            )
            return result
        try:
            payload = handler.invoke(
                {
                    "skill_name": skill_name,
                    "arguments": args,
                    "task": task,
                    "run_id": context.run_id,
                    "root": str(context.root),
                    "run_dir": str(context.run_dir) if context.run_dir else None,
                }
            )
            result = self._result_from_payload(skill_name, payload)
        except Exception as exc:  # noqa: BLE001 - adapter boundary returns structured failure
            result = SkillInvocationResult(
                ok=False,
                summary=f"Skill failed: {skill_name}",
                error=str(exc),
                status=self._classify_error(exc),
            )
        self._record_invocation(context, task, invocation_id, skill_name, args, decision, result)
        return result

    def _result_from_payload(
        self, skill_name: str, payload: dict[str, Any]
    ) -> SkillInvocationResult:
        raw_artifacts = payload.get("artifacts")
        artifacts: list[SkillArtifact] = []
        if isinstance(raw_artifacts, list):
            for item in raw_artifacts:
                if isinstance(item, str):
                    artifacts.append(SkillArtifact(path=item))
                elif isinstance(item, dict) and item.get("path"):
                    artifacts.append(
                        SkillArtifact(
                            path=str(item["path"]),
                            type=str(item.get("type") or "artifact"),
                            summary=str(item.get("summary") or ""),
                        )
                    )
        ok = bool(payload.get("ok", True))
        return SkillInvocationResult(
            ok=ok,
            summary=str(payload.get("summary") or f"Skill completed: {skill_name}"),
            data=(payload["data"] if isinstance(payload.get("data"), dict) else {}),
            artifacts=artifacts,
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
            status=str(payload.get("status") or ("success" if ok else "failure")),
        )

    def _record_invocation(
        self,
        context: RuntimeContext,
        task: dict[str, Any],
        invocation_id: str,
        skill_name: str,
        arguments: dict[str, Any],
        decision: dict[str, Any],
        result: SkillInvocationResult,
    ) -> None:
        if context.run_dir is None:
            return
        artifact_refs = self._record_artifacts(context, task, skill_name, result)
        path = context.run_dir / "skill_invocations.jsonl"
        record = {
            "schema_version": "0.1.0",
            "skill_invocation_id": invocation_id,
            "run_id": context.run_id,
            "task_id": str(task.get("task_id", "")),
            "skill_name": skill_name,
            "arguments": self._safe_arguments(arguments),
            "capability_decision": decision,
            "status": result.status,
            "ok": result.ok,
            "summary": result.summary,
            "error": result.error,
            "data": result.data,
            "artifacts": [artifact.to_dict() for artifact in result.artifacts],
            "artifact_refs": artifact_refs,
            "created_at": now_iso(),
        }
        JsonlStore(context.validator).append(path, record, schema_name="skill_invocation")
        UserProgressLogger(path.with_name("user_progress.jsonl"), context.validator).record(
            run_id=context.run_id,
            channel="tool",
            event_type="tool_output",
            phase="execute",
            status=self._progress_status(result),
            title=f"Skill {skill_name}",
            summary=result.summary,
            artifact_refs=artifact_refs,
            data={
                "adapter": "skill_workflow_artifact",
                "capability_type": "skill",
                "skill_invocation": record,
                "capability_decision": decision,
            },
            evidence_refs=[str(path), str(context.run_dir / "capability_decisions.jsonl")],
            call_chain=[self.actor, skill_name],
            execution_chain=[str(task.get("task_id", "")), "skill", skill_name],
        )

    def _record_artifacts(
        self,
        context: RuntimeContext,
        task: dict[str, Any],
        skill_name: str,
        result: SkillInvocationResult,
    ) -> list[str]:
        if context.run_dir is None or not result.artifacts:
            return []
        path = context.run_dir / "artifacts.jsonl"
        store = JsonlStore(context.validator)
        existing = store.read_all(path, "artifact") if path.exists() else []
        known = {artifact["path"]: artifact["artifact_id"] for artifact in existing}
        next_index = self._next_artifact_index(existing)
        refs: list[str] = []
        workspace = context.policy.get("workspace_envelope") or {}
        for skill_artifact in result.artifacts:
            if skill_artifact.path in known:
                refs.append(known[skill_artifact.path])
                continue
            artifact_id = f"artifact-{next_index:04d}"
            artifact = {
                "schema_version": "0.1.0",
                "artifact_id": artifact_id,
                "run_id": context.run_id,
                "task_id": str(task.get("task_id", "")),
                "type": skill_artifact.type,
                "path": skill_artifact.path,
                "absolute_path": str((context.root / skill_artifact.path).resolve()),
                "workspace_id": workspace.get("workspace_id"),
                "output_root": workspace.get("output_root"),
                "artifact_root": workspace.get("artifact_root"),
                "created_by": f"SkillAdapter:{skill_name}",
                "summary": skill_artifact.summary or result.summary,
                "created_at": now_iso(),
            }
            store.append(path, artifact, "artifact")
            refs.append(artifact_id)
            known[skill_artifact.path] = artifact_id
            next_index += 1
        return refs

    def _next_invocation_id(self, context: RuntimeContext) -> str:
        if context.run_dir is None:
            return "skill-0001"
        path = context.run_dir / "skill_invocations.jsonl"
        count = (
            len(JsonlStore(context.validator).read_all(path, schema_name=None))
            if path.exists()
            else 0
        )
        return f"skill-{count + 1:04d}"

    def _next_artifact_index(self, existing: list[dict[str, Any]]) -> int:
        highest = 0
        for artifact in existing:
            raw_id = str(artifact.get("artifact_id") or "")
            prefix, _, suffix = raw_id.partition("-")
            if prefix == "artifact" and suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def _safe_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            key: ("<redacted>" if self._sensitive_key(key) else value)
            for key, value in arguments.items()
        }

    def _progress_status(self, result: SkillInvocationResult) -> str:
        if result.ok:
            return "completed"
        if result.status == "denied":
            return "blocked"
        return "failed"

    def _classify_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if isinstance(exc, TimeoutError) or "timed out" in text:
            return "timeout"
        if isinstance(exc, ValueError) or "schema" in text or "argument" in text:
            return "contract_error"
        if "artifact" in text or "path" in text:
            return "artifact_error"
        return "execution_error"

    def _sensitive_key(self, key: str) -> bool:
        normalized = key.lower()
        return any(part in normalized for part in ["token", "secret", "password", "api_key"])


def _metadata_value(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip().strip("'\"")


def _first_paragraph(text: str) -> str:
    cleaned = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
    for block in re.split(r"\n\s*\n", cleaned):
        block = block.strip()
        if block and not block.startswith("#"):
            return " ".join(line.strip() for line in block.splitlines())
    return ""


def _load_skill_body_and_manifest(path: Path) -> tuple[str, list[str]]:
    """Return the SKILL.md body (frontmatter stripped) and a manifest of bundled sibling files."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", []
    body = re.sub(r"^\s*---.*?---", "", text, flags=re.DOTALL).strip() or text.strip()
    files: list[str] = []
    parent = path.parent
    if parent.exists():
        files = sorted(
            item.relative_to(parent).as_posix()
            for item in parent.rglob("*")
            if item.is_file() and item.name != "SKILL.md"
        )
    return body, files


def _parameter_contract(text: str) -> dict[str, Any]:
    raw = _metadata_value(text, "parameters") or _metadata_value(text, "parameter_contract")
    if not raw:
        return {}
    return {"summary": raw}


def _artifact_types(text: str) -> list[str]:
    raw = _metadata_value(text, "artifacts") or _metadata_value(text, "artifact_types")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _scope_rank(scope: str) -> int:
    return {"global": 0, "workspace": 1}.get(scope, 2)


def _prefer_skill(
    current: SkillDefinition | None,
    candidate: SkillDefinition,
) -> SkillDefinition:
    if current is None:
        return candidate
    if _scope_rank(candidate.scope) >= _scope_rank(current.scope):
        return candidate
    return current
