"""Bounded Review tools on a disposable copy; this is NOT an OS sandbox.

No promotion, external adapters, permission grants, or semantic verification rules.
Shell keeps the local execution permissions and limitations of RunTestsTool.
"""
from __future__ import annotations

import hashlib
import json
import math
import stat
from pathlib import Path
import tempfile
import time
from dataclasses import replace

from asteria_runtime.core.candidate_workspace import EXCLUDED_NAMES
from asteria_runtime.core.agent_tool_surface import model_tool_surface_for_task
from asteria_runtime.core.content_preservation import PROTECTED
from asteria_runtime.core.review_artifacts import collect_review_artifacts
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.tool_batch_result import ToolBatchError
from asteria_runtime.models.base import ChatRequest
from asteria_runtime.security.path_guard import PathGuard
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.tools.command_tools import RunCommandTool, RunTestsTool
from asteria_runtime.tools.file_tools import ListFilesTool, ReadFileTool
from asteria_runtime.tools.search_tools import FindFilesTool, SearchTextTool
from asteria_runtime.tools.registry import ToolRegistry

REVIEW_TOOLS = ["read_file", "list_files", "find_files", "search_text", "run_tests"]
REVIEW_TURN_CONTRACT = (
    'For an intermediate tool turn return {"narration":"...","tool_calls":'
    '[{"tool_name":"<available tool>","args":{...}}],"done":false}. '
    'For the final turn return the EvalReport JSON directly, without tool_calls. '
    'Return one JSON object per turn. Tool definitions and execution limits are in review_tools.'
)


class ReviewTools:
    """A tool runner using the ordinary gateway, with auditable copy/evidence boundaries."""

    def __init__(self, context: RuntimeContext, artifacts: dict, goal: dict, board: dict,
                 *, total_seconds: float = 120, max_files: int = 10_000,
                 max_bytes: int = 134_217_728) -> None:
        self.context, self.artifacts, self.goal, self.board = context, artifacts, goal, board
        self.started = time.monotonic()
        self.total_seconds, self.max_files, self.max_bytes = total_seconds, max_files, max_bytes
        self.allowed = [] if context.policy.get("permission_mode") == "ask_everything" else list(REVIEW_TOOLS)
        self.task = {"task_id": f"review-{artifacts['evidence_id']}", "task_kind": "verification",
                     "risk": "low", "parallel_safety": "readonly",
                     "write_scope": [], "allowed_tools": self.allowed, "allowed_mcp": [], "allowed_skills": []}
        self._temporary: tempfile.TemporaryDirectory | None = None
        self.copy_context: RuntimeContext | None = None
        self.manifest: list[dict] = []
        self.observations: list[dict] = []
        self.errors: list[str] = []
        self.stop_reason = "not_started"
        self.model_calls = 0
        self.dispatched = False
        self.path = context.run_dir / f"{artifacts['evidence_id']}-validation.json" if context.run_dir else None
        self._save()

    def remaining(self) -> float:
        return max(0, self.total_seconds - (time.monotonic() - self.started))

    def exhausted(self) -> bool:
        return self.remaining() < 1 or bool(self.context.budget and self.context.budget.cost_hard_stop_reached())

    def describe(self) -> dict:
        surface = model_tool_surface_for_task(REVIEW_TOOLS, self.task)
        return {"tools": [tool for tool in surface["tools"] if tool["task_allowed"]], "max_iterations": 8,
                "total_seconds": self.total_seconds, "command_max_seconds": 60,
                "execution_root": "disposable filtered project copy; never promoted",
                "is_os_sandbox": False, "permissions": self.context.policy.get("permissions", {}),
                "excluded": sorted(EXCLUDED_NAMES) + ["protected paths", "symlinks/junctions"],
                "copy_limits": {"files": self.max_files, "bytes": self.max_bytes},
                "permission_escalation": "unavailable; denied checks return failed observations",
                "mode": self.context.policy.get("permission_mode", "reviewed_auto"),
                "evidence_ref": str(self.path)}

    def bounded_client(self, client):
        owner = self

        class Client:
            def chat(self, request: ChatRequest):
                owner.model_calls += 1
                seconds = max(1, math.floor(owner.remaining()))
                metadata = dict(request.metadata)
                metadata["deadline_ms"] = min(int(metadata.get("deadline_ms") or seconds * 1000), seconds * 1000)
                seconds = max(1, metadata["deadline_ms"] // 1000)
                return client.chat(replace(request, timeout_seconds=seconds, metadata=metadata))

        return Client()

    def _prepare(self) -> RuntimeContext:
        if self.copy_context is not None:
            return self.copy_context
        self._temporary = tempfile.TemporaryDirectory(prefix="asteria-review-")
        destination = Path(self._temporary.name).resolve()
        policy = {**self.context.policy, "protected_paths": [*PROTECTED, *self.context.policy.get("protected_paths", [])]}
        guard = PathGuard(self.context.root, policy["protected_paths"])
        total = 0
        visited = 0

        def copy(directory: Path) -> None:
            nonlocal total, visited
            for path in sorted(directory.iterdir()):
                visited += 1
                if visited > 50_000:
                    raise ValueError("Review copy entry limit exceeded")
                if self.exhausted():
                    raise TimeoutError("Review copy time or shared goal budget exhausted")
                if path.name in EXCLUDED_NAMES or path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    continue
                try:
                    guard.resolve_for_read(path)
                except PermissionError:
                    continue  # Never open protected files, even for a hash.
                relative = path.relative_to(self.context.root)
                if path.is_dir():
                    (destination / relative).mkdir(parents=True, exist_ok=True)
                    copy(path)
                elif path.is_file():
                    size = path.stat().st_size
                    if len(self.manifest) >= self.max_files or total + size > self.max_bytes:
                        raise ValueError("Review copy file/byte limit exceeded; no partial copy is executable")
                    with path.open("rb") as stream:
                        content = stream.read(self.max_bytes - total + 1)
                    if total + len(content) > self.max_bytes:
                        raise ValueError("Review copy byte limit exceeded while reading")
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    target.chmod(stat.S_IMODE(path.stat().st_mode))
                    self.manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(content).hexdigest(),
                                          "bytes": len(content)})
                    total += len(content)

        copy(self.context.root)
        copied = replace(self.context, root=destination, policy=policy,
                         agent_dir_override=self.context.agent_dir, run_dir_override=self.context.run_dir)
        snapshot = collect_review_artifacts(copied, self.goal, self.board)
        expected = [(r["path"], r["status"], r["content_sha256"]) for r in self.artifacts["files"]]
        actual = [(r["path"], r["status"], r["content_sha256"]) for r in snapshot["files"]]
        if expected != actual:
            raise ValueError("Review copy does not match the bound current artifact snapshot")
        self.copy_context = copied
        self._save()
        return copied

    def run_tool_calls(self, calls, task, context, stop_on_failure=True, stop_verification_on_fatal=False):
        self.dispatched = True
        if not self.allowed:
            self.errors.append("selected_check_denied:ask_everything")
            raise PermissionError("Review tools require an execution-capable permission mode")
        try:
            copied = self._prepare()
        except Exception as exc:
            self.errors.append(f"copy_unavailable:{type(exc).__name__}")
            raise
        registry = ToolRegistry()
        # Register a restricted surface, not merely a model-facing allowlist. No adapters.
        for tool in [ReadFileTool(), ListFilesTool(), FindFilesTool(), SearchTextTool()]:
            registry.register(tool)
        registry.register(RunTestsTool(RunCommandTool(default_timeout_seconds=60)))
        gateway = ToolExecutionGateway(registry, ToolPermissionPolicy(copied.root, copied.validator),
                                       actor="ReviewAgent", agent_id="ReviewAgent")
        results = []
        for index, call in enumerate(calls):
            if self.exhausted():
                self.errors.append("selected_check_not_executed:budget_or_time")
                raise ToolBatchError(results, call, TimeoutError("Review execution budget exhausted"), calls[index + 1:])
            args = dict(call.get("args") or {})
            if call.get("tool_name") == "run_tests":
                timeout = args.get("timeout_seconds", 60)
                if not isinstance(timeout, bool) and isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0:
                    args["timeout_seconds"] = min(timeout, 60, max(1, math.floor(self.remaining())))
            try:
                results.extend(gateway.run_tool_calls([{**call, "args": args}], self.task, copied, stop_on_failure=False))
            except ToolBatchError as exc:
                raise ToolBatchError(results, call, exc.cause, calls[index + 1:]) from exc
        for result in results:
            observed = getattr(result, "harness_observation", None)
            if observed is not None:
                self.observations.append({"tool_call_id": observed.data.get("tool_call_id"),
                                          "tool_name": observed.tool_name, "ok": observed.ok})
        self._save()
        return results

    def finish(self, reason: str) -> dict:
        self.stop_reason = reason
        if self.context.run_dir is not None:
            from asteria_runtime.storage.jsonl_store import JsonlStore
            ledger = self.context.run_dir / "tool_observations.jsonl"
            if ledger.exists():
                rows = [row for row in JsonlStore(self.context.validator).read_all(ledger, "tool_observation")
                        if row["task_id"] == self.task["task_id"]]
                self.observations = [
                    {"observation_id": row["observation_id"], "tool_call_id": row["tool_call_id"],
                     "tool_name": row["tool_name"], "ok": row["ok"], "status": row["status"]}
                    for row in rows
                ]
                for row in rows:
                    observed = row["observation"]
                    if (row["status"] == "denied" or observed.get("error") in {"timeout", "invalid_timeout"}
                            or observed.get("data", {}).get("error_type") in {"PermissionError", "ToolPermissionDenied"}):
                        self.errors.append(f"selected_check_unavailable:{row['tool_call_id']}")
        if self.copy_context is not None:
            for entry in self.manifest:
                for root, label in [(self.copy_context.root, "copied_input_changed"),
                                    (self.context.root, "source_changed_during_review")]:
                    path = root / entry["path"]
                    try:
                        members = [path, *list(path.parents)[:len(Path(entry["path"]).parts) - 1]]
                        linked = any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in members)
                        # Never follow a command-replaced symlink, junction, or huge replacement file.
                        changed = linked or path.stat().st_size != entry["bytes"]
                        if not changed:
                            changed = hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
                    except OSError:
                        changed = True
                    if changed:
                        self.errors.append(f"{label}:{entry['path']}")
        data = self._save()
        if self._temporary is not None:
            self._temporary.cleanup()
        return data

    def _save(self) -> dict:
        data = {"schema_version": "0.1.0", "run_id": self.context.run_id,
                "artifact_evidence_id": self.artifacts["evidence_id"], "task_id": self.task["task_id"],
                "is_os_sandbox": False, "promoted": False, "stop_reason": self.stop_reason,
                "copy_created": self.copy_context is not None, "source_manifest": self.manifest,
                "source_manifest_sha256": hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest(),
                "observations": self.observations, "errors": self.errors,
                "limits": self.describe()}
        if self.path is not None:
            JsonStore(self.context.validator).write(self.path, data, "review_validation")
        return data
