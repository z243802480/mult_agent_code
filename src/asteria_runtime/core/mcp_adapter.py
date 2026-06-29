from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from asteria_runtime.core.budget import BudgetExceededError
from asteria_runtime.core.capability_decision_recorder import CapabilityDecisionRecorder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


class McpSession(Protocol):
    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: list[str]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    framing: str = "jsonl"


@dataclass(frozen=True)
class McpInvocationResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    status: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "error": self.error,
            "status": self.status,
        }


@dataclass(frozen=True)
class McpAdapterConfig:
    servers: list[McpServerConfig] = field(default_factory=list)
    session_call_timeout_seconds: int = 60
    retry_attempts: int = 0


class StdioMcpSession:
    """Minimal MCP stdio JSON-RPC session."""

    def __init__(self, config: McpServerConfig) -> None:
        if not config.command:
            raise ValueError("MCP server command is required")
        self.config = config
        self._next_id = 1
        self._initialized = False
        command = [shutil.which(config.command[0]) or config.command[0], *config.command[1:]]
        self._process = subprocess.Popen(
            command,
            cwd=str(config.cwd) if config.cwd else None,
            env={**os.environ, **config.env} if config.env else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        response = self._read_response(request_id)
        if response.get("error"):
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
        result = response.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._kill_process_tree()

    def _kill_process_tree(self) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        self._process.kill()

    def _write(self, payload: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise RuntimeError("MCP stdin is closed")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.config.framing == "content-length":
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            self._process.stdin.write(header + body)
        else:
            self._process.stdin.write(body + b"\n")
        self._process.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "asteria-runtime",
                        "version": "0.1.0",
                    },
                },
            }
        )
        response = self._read_response(request_id)
        if response.get("error"):
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
        self._notify("notifications/initialized")
        self._initialized = True

    def _read(self) -> dict[str, Any]:
        if self.config.framing == "content-length":
            return self._read_content_length()
        return self._read_jsonl()

    def _read_jsonl(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise RuntimeError("MCP stdout is closed")
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server closed stdout: {self._stderr_tail()}")
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded or not decoded.startswith("{"):
                continue
            response = json.loads(decoded)
            if not isinstance(response, dict):
                raise RuntimeError("MCP response is not a JSON object")
            return response

    def _read_content_length(self) -> dict[str, Any]:
        if self._process.stdout is None:
            raise RuntimeError("MCP stdout is closed")
        while True:
            headers: dict[str, str] = {}
            while True:
                line = self._process.stdout.readline()
                if not line:
                    raise RuntimeError(f"MCP server closed stdout: {self._stderr_tail()}")
                decoded = line.decode("ascii", errors="replace").strip()
                if not decoded:
                    break
                key, _, value = decoded.partition(":")
                headers[key.lower()] = value.strip()
            length = int(headers.get("content-length") or "0")
            if length <= 0:
                continue
            body = self._process.stdout.read(length)
            response = json.loads(body.decode("utf-8"))
            if not isinstance(response, dict):
                raise RuntimeError("MCP response is not a JSON object")
            return response

    def _read_response(self, request_id: int) -> dict[str, Any]:
        while True:
            response = self._read()
            if response.get("id") == request_id:
                return response

    def _stderr_tail(self) -> str:
        if self._process.stderr is None:
            return ""
        try:
            chunk = self._process.stderr.read(4000)
        except OSError:
            return ""
        return chunk.decode("utf-8", errors="replace")[-1000:]


class McpAdapter:
    """External MCP protocol/session adapter; not a ToolExecutionGateway wrapper."""

    def __init__(
        self,
        sessions: dict[str, McpSession],
        *,
        actor: str = "McpAdapter",
        session_call_timeout_seconds: int = 60,
        retry_attempts: int = 0,
    ) -> None:
        self.sessions = sessions
        self.actor = actor
        self.session_call_timeout_seconds = session_call_timeout_seconds
        self.retry_attempts = max(0, retry_attempts)

    @classmethod
    def from_configs(cls, configs: list[McpServerConfig]) -> McpAdapter:
        return cls({config.name: StdioMcpSession(config) for config in configs})

    @classmethod
    def from_adapter_config(cls, config: McpAdapterConfig) -> McpAdapter:
        return (
            cls.from_configs(config.servers)
            .with_timeout(config.session_call_timeout_seconds)
            .with_retries(config.retry_attempts)
        )

    def with_timeout(self, timeout_seconds: int) -> McpAdapter:
        self.session_call_timeout_seconds = timeout_seconds
        return self

    def with_retries(self, retry_attempts: int) -> McpAdapter:
        self.retry_attempts = max(0, retry_attempts)
        return self

    def invoke_tool(
        self,
        *,
        context: RuntimeContext,
        task: dict[str, Any],
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpInvocationResult:
        invocation_id = self._next_invocation_id(context)
        capability_name = f"{server_name}/{tool_name}"
        decision = CapabilityDecisionRecorder(self.actor).decide_mcp(
            capability_name,
            task=task,
            context=context,
            mcp_invocation_id=invocation_id,
        )
        if decision["decision"] == "deny":
            result = McpInvocationResult(
                ok=False,
                summary=f"MCP denied: {capability_name}",
                error=decision["reason"],
                status="denied",
            )
            self._record_invocation(
                context,
                task,
                invocation_id,
                server_name,
                tool_name,
                arguments or {},
                decision,
                result,
            )
            return result
        if context.budget:
            try:
                context.budget.record_tool_call(f"mcp.{server_name}/{tool_name}")
            except BudgetExceededError as exc:
                result = McpInvocationResult(
                    ok=False,
                    summary=f"MCP denied by budget: {capability_name}",
                    error=str(exc),
                    status="denied",
                )
                self._record_invocation(
                    context,
                    task,
                    invocation_id,
                    server_name,
                    tool_name,
                    arguments or {},
                    decision,
                    result,
                )
                return result
        session = self.sessions.get(server_name)
        if session is None:
            result = McpInvocationResult(
                ok=False,
                summary=f"MCP server not configured: {server_name}",
                error="mcp_server_not_configured",
                status="config_error",
            )
            self._record_invocation(
                context,
                task,
                invocation_id,
                server_name,
                tool_name,
                arguments or {},
                decision,
                result,
            )
            return result
        try:
            payload, attempts = self._call_session_with_retries(
                session,
                "tools/call",
                {"name": tool_name, "arguments": arguments or {}},
            )
            result = McpInvocationResult(
                ok=True,
                summary=f"MCP tool completed: {capability_name}",
                data={
                    "server": server_name,
                    "tool": tool_name,
                    "response": payload,
                    "attempts": attempts,
                },
            )
        except Exception as exc:  # noqa: BLE001 - adapter boundary returns structured failure
            result = McpInvocationResult(
                ok=False,
                summary=f"MCP tool failed: {capability_name}",
                error=str(exc),
                status=self._classify_error(exc),
            )
        self._record_invocation(
            context, task, invocation_id, server_name, tool_name, arguments or {}, decision, result
        )
        return result

    def close(self) -> None:
        for session in self.sessions.values():
            session.close()

    def _call_session(
        self,
        session: McpSession,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(session.call, method, params)
        try:
            return future.result(timeout=self.session_call_timeout_seconds)
        except TimeoutError as exc:
            session.close()
            raise TimeoutError(
                f"MCP session call timed out after {self.session_call_timeout_seconds}s"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _call_session_with_retries(
        self,
        session: McpSession,
        method: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        attempts = self.retry_attempts + 1
        last_error: Exception | None = None
        for index in range(attempts):
            try:
                return self._call_session(session, method, params), index + 1
            except Exception as exc:  # noqa: BLE001 - retry boundary returns structured failure
                last_error = exc
                if index >= attempts - 1 or not self._retryable(exc):
                    raise
        raise RuntimeError(str(last_error) if last_error else "MCP call failed")

    def _record_invocation(
        self,
        context: RuntimeContext,
        task: dict[str, Any],
        invocation_id: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        decision: dict[str, Any],
        result: McpInvocationResult,
    ) -> None:
        if context.run_dir is None:
            return
        path = context.run_dir / "mcp_invocations.jsonl"
        record = {
            "schema_version": "0.1.0",
            "mcp_invocation_id": invocation_id,
            "run_id": context.run_id,
            "task_id": str(task.get("task_id", "")),
            "server_name": server_name,
            "tool_name": tool_name,
            "arguments": self._safe_arguments(arguments),
            "capability_decision": decision,
            "status": result.status,
            "error_class": result.status if not result.ok else None,
            "ok": result.ok,
            "summary": result.summary,
            "error": result.error,
            "data": result.data,
            "retry_attempts": self.retry_attempts,
            "created_at": now_iso(),
        }
        JsonlStore(context.validator).append(path, record, schema_name="mcp_invocation")
        UserProgressLogger(path.with_name("user_progress.jsonl"), context.validator).record(
            run_id=context.run_id,
            channel="tool",
            event_type="tool_output",
            phase="execute",
            status=self._progress_status(result),
            title=f"MCP {server_name}/{tool_name}",
            summary=result.summary,
            data={
                "adapter": "mcp_protocol_session",
                "capability_type": "mcp",
                "mcp_invocation": record,
                "capability_decision": decision,
            },
            evidence_refs=[str(path), str(context.run_dir / "capability_decisions.jsonl")],
            call_chain=[self.actor, server_name, tool_name],
            execution_chain=[str(task.get("task_id", "")), "mcp", server_name, tool_name],
        )

    def _next_invocation_id(self, context: RuntimeContext) -> str:
        if context.run_dir is None:
            return "mcp-0001"
        path = context.run_dir / "mcp_invocations.jsonl"
        count = (
            len(JsonlStore(context.validator).read_all(path, schema_name=None))
            if path.exists()
            else 0
        )
        return f"mcp-{count + 1:04d}"

    def _safe_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            key: ("<redacted>" if self._sensitive_key(key) else value)
            for key, value in arguments.items()
        }

    def _progress_status(self, result: McpInvocationResult) -> str:
        if result.ok:
            return "completed"
        if result.status == "denied":
            return "blocked"
        return "failed"

    def _classify_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if isinstance(exc, TimeoutError) or "timed out" in text:
            return "timeout"
        if "json" in text or "jsonrpc" in text or "protocol" in text:
            return "protocol_error"
        if "closed stdout" in text or "stdin is closed" in text or "server closed" in text:
            return "session_error"
        return "execution_error"

    def _retryable(self, exc: Exception) -> bool:
        return self._classify_error(exc) in {"timeout", "session_error", "execution_error"}

    def _sensitive_key(self, key: str) -> bool:
        normalized = key.lower()
        return any(part in normalized for part in ["token", "secret", "password", "api_key"])


def mcp_adapter_config_from_policy(
    policy: dict[str, Any], *, root: Path | None = None
) -> McpAdapterConfig:
    raw = policy.get("mcp")
    config = raw if isinstance(raw, dict) else {}
    timeout = int(config.get("session_call_timeout_seconds") or 60)
    retry_attempts = int(config.get("retry_attempts") or 0)
    raw_servers = config.get("servers")
    servers: list[McpServerConfig] = []
    if isinstance(raw_servers, list):
        for item in raw_servers:
            if not isinstance(item, dict):
                continue
            parsed = mcp_server_config_from_dict(item, root=root)
            if parsed is not None:
                servers.append(parsed)
    return McpAdapterConfig(
        servers=servers,
        session_call_timeout_seconds=timeout,
        retry_attempts=retry_attempts,
    )


def mcp_adapter_config_from_product_policy(
    product_policy: dict[str, Any],
    *,
    workspace_policy: dict[str, Any] | None = None,
    root: Path | None = None,
) -> McpAdapterConfig:
    """Build MCP config from product-level servers plus workspace runtime limits.

    MCP servers are product/user connectors. Workspaces can tune call limits, but
    they should not be the default place to redefine the server catalog.
    """

    product_config = mcp_adapter_config_from_policy(product_policy, root=root)
    raw_workspace_mcp = workspace_policy.get("mcp") if isinstance(workspace_policy, dict) else None
    workspace_mcp: dict[str, Any] = raw_workspace_mcp if isinstance(raw_workspace_mcp, dict) else {}
    timeout = int(
        workspace_mcp.get(
            "session_call_timeout_seconds",
            product_config.session_call_timeout_seconds,
        )
    )
    retry_attempts = int(workspace_mcp.get("retry_attempts", product_config.retry_attempts))
    return McpAdapterConfig(
        servers=product_config.servers,
        session_call_timeout_seconds=timeout,
        retry_attempts=retry_attempts,
    )


def mcp_server_config_from_dict(
    data: dict[str, Any],
    *,
    root: Path | None = None,
) -> McpServerConfig | None:
    name = str(data.get("name") or "").strip()
    raw_command = data.get("command")
    if not name or not isinstance(raw_command, list) or not raw_command:
        return None
    command = [str(part) for part in raw_command]
    raw_cwd = data.get("cwd")
    cwd = None
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        cwd_path = Path(raw_cwd)
        cwd = (
            (root / cwd_path).resolve()
            if root and not cwd_path.is_absolute()
            else cwd_path.resolve()
        )
    raw_env = data.get("env")
    env = {str(k): str(v) for k, v in raw_env.items()} if isinstance(raw_env, dict) else {}
    framing = str(data.get("framing") or "jsonl")
    if framing not in {"jsonl", "content-length"}:
        framing = "jsonl"
    return McpServerConfig(name=name, command=command, cwd=cwd, env=env, framing=framing)


def mcp_invocation_summary(run_dir: Path, validator: Any) -> dict[str, Any]:
    path = run_dir / "mcp_invocations.jsonl"
    if not path.exists():
        return {
            "schema_version": "0.1.0",
            "total": 0,
            "completed": 0,
            "failed": 0,
            "denied": 0,
            "by_status": {},
            "latest": [],
            "consumer_summary": "No MCP invocations recorded.",
        }
    invocations = JsonlStore(validator).read_all(path, schema_name=None)
    by_status: dict[str, int] = {}
    for item in invocations:
        status = str(item.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    latest = [
        {
            "mcp_invocation_id": item.get("mcp_invocation_id"),
            "server_name": item.get("server_name"),
            "tool_name": item.get("tool_name"),
            "status": item.get("status"),
            "summary": item.get("summary"),
            "created_at": item.get("created_at"),
        }
        for item in invocations[-5:]
    ]
    return {
        "schema_version": "0.1.0",
        "total": len(invocations),
        "completed": len([item for item in invocations if item.get("ok") is True]),
        "failed": len(
            [
                item
                for item in invocations
                if item.get("ok") is not True and item.get("status") != "denied"
            ]
        ),
        "denied": by_status.get("denied", 0),
        "by_status": by_status,
        "latest": latest,
        "consumer_summary": _mcp_consumer_summary(invocations, by_status),
    }


def _mcp_consumer_summary(invocations: list[dict[str, Any]], by_status: dict[str, int]) -> str:
    if not invocations:
        return "No MCP invocations recorded."
    failures = len([item for item in invocations if item.get("ok") is not True])
    if failures:
        return (
            f"MCP recorded {len(invocations)} invocation(s), with failures by status: {by_status}."
        )
    return f"MCP recorded {len(invocations)} successful invocation(s)."
