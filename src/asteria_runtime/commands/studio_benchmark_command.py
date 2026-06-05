from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_MAIN_EVENTS = {
    "user_message",
    "assistant_delta",
    "final_answer",
    "permission_request",
}

DEFAULT_REQUIRED_USER_PROGRESS_KINDS = {
    "plan",
    "tool_use",
    "tool_result",
    "file_change",
    "verification",
    "final",
}

RAW_MAIN_EVENT_TYPES = {
    "model_start",
    "model_delta",
    "model_end",
    "model_error",
    "reasoning_delta",
}

RAW_MAIN_PATTERNS = (
    "<think>",
    "schema_version",
    "agent_loop_decision",
    "provider route",
    "model route",
    "model-check",
    "gate-status",
    "runtime stdout",
    "stdout:",
    "stderr:",
)

RUN_SCOPE_CHECKS = {
    "task_progress",
    "permission_or_result",
    "inspector_separation",
    "user_progress_protocol",
    "user_progress_semantic_contract",
    "process_kind_coverage",
    "main_thread_no_raw_model_delta",
    "inspector_model_delta_boundary",
}


@dataclass(frozen=True)
class StudioBenchmarkResult:
    ok: bool
    score: float
    ready_threshold: float
    evaluated_sessions: int
    user_progress_events: int
    benchmark_tasks: int
    checks: list[dict[str, Any]]
    recommendations: list[str]
    manifest_path: str
    scope: str = "workspace"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "score": self.score,
            "ready_threshold": self.ready_threshold,
            "evaluated_sessions": self.evaluated_sessions,
            "user_progress_events": self.user_progress_events,
            "benchmark_tasks": self.benchmark_tasks,
            "checks": self.checks,
            "recommendations": self.recommendations,
            "manifest_path": self.manifest_path,
            "scope": self.scope,
        }

    def to_text(self) -> str:
        status = "ready" if self.ok else "not_ready"
        lines = [
            f"Studio benchmark: {status}",
            f"- scope: {self.scope}",
            f"- score: {self.score:.2f} (threshold {self.ready_threshold:.2f})",
            f"- evaluated sessions: {self.evaluated_sessions}",
            f"- user progress events: {self.user_progress_events}",
            f"- benchmark tasks: {self.benchmark_tasks}",
            f"- manifest: {self.manifest_path}",
        ]
        if self.checks:
            lines.append("- checks:")
            for check in self.checks:
                mark = "pass" if check["ok"] else "fail"
                lines.append(f"  - {mark}: {check['name']} - {check['summary']}")
        if self.recommendations:
            lines.append("- recommendations:")
            lines.extend(f"  - {item}" for item in self.recommendations)
        return "\n".join(lines)


class StudioBenchmarkCommand:
    def __init__(
        self,
        root: Path,
        manifest: Path | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.root = root
        self.manifest = manifest or root / "benchmarks" / "studio_user_tasks.json"
        self.session_id = session_id
        self.run_id = run_id

    def run(self) -> StudioBenchmarkResult:
        manifest = self._read_json(self.manifest)
        sessions = [] if self.run_id and not self.session_id else self._load_sessions()
        events = [event for session in sessions for event in session["events"]]
        user_progress_events = self._load_user_progress_events()
        checks = self._evaluate(events, user_progress_events, manifest)
        score = round(sum(1 for check in checks if check["ok"]) / max(1, len(checks)), 4)
        threshold = float(manifest.get("minimum_ready_score", 0.8))
        recommendations = self._recommendations(checks, sessions, user_progress_events, manifest)
        blocking_names = (
            RUN_SCOPE_CHECKS
            if self.run_id
            else {"session_activity", "benchmark_task_coverage"}
        )
        blocking_failures = {
            check["name"]
            for check in checks
            if not check["ok"] and check["name"] in blocking_names
        }
        return StudioBenchmarkResult(
            ok=score >= threshold and not blocking_failures,
            score=score,
            ready_threshold=threshold,
            evaluated_sessions=len(sessions),
            user_progress_events=len(user_progress_events),
            benchmark_tasks=len(manifest.get("tasks") or []),
            checks=checks,
            recommendations=recommendations,
            manifest_path=str(self.manifest),
            scope=f"run:{self.run_id}" if self.run_id else "workspace",
        )

    def _load_sessions(self) -> list[dict[str, Any]]:
        sessions_root = self.root / ".asteria" / "studio" / "sessions"
        if not sessions_root.exists():
            return []
        session_dirs = [path for path in sessions_root.iterdir() if path.is_dir()]
        if self.session_id:
            session_dirs = [sessions_root / self.session_id]
        sessions = []
        for session_dir in sorted(session_dirs, key=lambda item: item.name):
            events_path = session_dir / "events.jsonl"
            if not events_path.exists():
                continue
            sessions.append(
                {
                    "session_id": session_dir.name,
                    "events": self._read_jsonl(events_path),
                }
            )
        return sessions

    def _load_user_progress_events(self) -> list[dict[str, Any]]:
        runs_root = self.root / ".asteria" / "runs"
        if not runs_root.exists():
            return []
        if self.run_id:
            return self._read_jsonl(runs_root / self.run_id / "user_progress.jsonl")
        events: list[dict[str, Any]] = []
        for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda item: item.name):
            events.extend(self._read_jsonl(run_dir / "user_progress.jsonl"))
        return events

    def _evaluate(
        self,
        events: list[dict[str, Any]],
        user_progress_events: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        tasks = self._manifest_tasks(manifest)
        event_types = {str(event.get("type")) for event in events}
        semantic_user_progress = [
            event for event in user_progress_events if str(event.get("transcript_kind") or "")
        ]
        main_user_progress = [
            event for event in semantic_user_progress if event.get("display_level") != "inspector"
        ]
        progress_kinds = {
            str(event.get("transcript_kind"))
            for event in main_user_progress
            if str(event.get("transcript_kind") or "")
        }
        has_task_progress = bool(
            progress_kinds & {"plan", "todo_update", "tool_use", "tool_result", "verification"}
        )
        has_permission_or_result = bool(
            {"permission_request", "final_answer"} & event_types
        ) or bool(
            progress_kinds & {"permission_request", "decision_request", "ask", "stop", "final"}
        )
        required_kinds = self._required_user_progress_kinds(manifest)
        final_answers = [event for event in events if str(event.get("type")) == "final_answer"]
        good_final_answers = [event for event in final_answers if self._is_user_facing_final(event)]
        inspector_events = [event for event in events if event.get("display_level") == "inspector"]
        raw_main_leaks = self._raw_main_leaks(events, semantic_user_progress)
        inspector_model_delta_ok = all(
            event.get("display_level") == "inspector"
            for event in semantic_user_progress
            if event.get("channel") == "model" and event.get("event_type") == "delta"
        )
        checks = [
            self._check(
                "session_activity",
                bool(events),
                "Studio has recorded session events."
                if events
                else "No Studio session events were found.",
            ),
            self._check(
                "user_message",
                "user_message" in event_types,
                "User goals are persisted in the thread."
                if "user_message" in event_types
                else "No user_message event found.",
            ),
            self._check(
                "immediate_acknowledgement",
                "assistant_delta" in event_types,
                "Assistant acknowledgement is visible."
                if "assistant_delta" in event_types
                else "No assistant acknowledgement event found.",
            ),
            self._check(
                "task_progress",
                has_task_progress,
                "Runtime-native task progress is visible in user semantics."
                if has_task_progress
                else "No semantic runtime progress event found.",
            ),
            self._check(
                "permission_or_result",
                has_permission_or_result,
                "The task reaches a permission, decision, stop, ask, or final result surface."
                if has_permission_or_result
                else "No permission, decision, stop, ask, or final result event found.",
            ),
            self._check(
                "final_answer_quality",
                bool(good_final_answers),
                "Final answers start with a user-facing answer/result, not backend logs."
                if good_final_answers
                else "No user-facing final answer found; final output may be process logs or missing.",
            ),
            self._check(
                "inspector_separation",
                not raw_main_leaks and (bool(inspector_events) or bool(user_progress_events)),
                "Raw runtime/model details stay in Inspector or evidence files."
                if not raw_main_leaks and (bool(inspector_events) or bool(user_progress_events))
                else "Raw runtime/model details leak into the main user thread.",
            ),
            self._check(
                "benchmark_catalog",
                bool(tasks),
                "User task benchmark catalog is present."
                if tasks
                else "Benchmark catalog has no tasks.",
            ),
            self._check(
                "benchmark_task_coverage",
                self._task_coverage(tasks) == len(tasks) and bool(tasks),
                f"{self._task_coverage(tasks)}/{len(tasks)} benchmark tasks have matching Studio sessions."
                if tasks
                else "No benchmark tasks are defined.",
            ),
            self._check(
                "user_progress_protocol",
                bool(user_progress_events),
                "Runtime-native user_progress events are available."
                if user_progress_events
                else "No runtime-native user_progress events were found.",
            ),
            self._check(
                "user_progress_semantic_contract",
                bool(main_user_progress)
                and all(str(event.get("transcript_kind") or "") for event in main_user_progress),
                "Main user_progress events carry transcript_kind semantics."
                if main_user_progress
                and all(str(event.get("transcript_kind") or "") for event in main_user_progress)
                else "Main user_progress events are missing transcript_kind semantics.",
            ),
            self._check(
                "process_kind_coverage",
                required_kinds.issubset(progress_kinds),
                f"Covered user progress kinds: {', '.join(sorted(progress_kinds & required_kinds))}."
                if progress_kinds & required_kinds
                else f"No required user progress kinds covered: {', '.join(sorted(required_kinds))}.",
            ),
            self._check(
                "main_thread_no_raw_model_delta",
                not raw_main_leaks,
                "Main thread/user_progress has no raw model delta or backend contract leaks."
                if not raw_main_leaks
                else f"Raw main leaks detected: {', '.join(raw_main_leaks)}.",
            ),
            self._check(
                "inspector_model_delta_boundary",
                inspector_model_delta_ok,
                "Raw model deltas are Inspector-only."
                if inspector_model_delta_ok
                else "Raw model deltas must be display_level=inspector.",
            ),
        ]
        if self.run_id:
            return [check for check in checks if check["name"] in RUN_SCOPE_CHECKS]
        return checks

    def _recommendations(
        self,
        checks: list[dict[str, Any]],
        sessions: list[dict[str, Any]],
        user_progress_events: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> list[str]:
        failed = {check["name"] for check in checks if not check["ok"]}
        recommendations = []
        if not sessions and not self.run_id:
            recommendations.append(
                "Run the Studio benchmark tasks through the UI and preserve session events."
            )
        if "task_progress" in failed:
            recommendations.append(
                "Make Runtime write plan/tool/verification user_progress events instead of asking Studio to infer progress from raw events."
            )
        if "permission_or_result" in failed:
            recommendations.append(
                "Make every task reach either a permission, decision, ask, stop, or final answer surface."
            )
        if "final_answer_quality" in failed:
            recommendations.append(
                "Make final answers begin with the answer/result users asked for; move process summaries and raw paths after the answer."
            )
        if "inspector_separation" in failed or "main_thread_no_raw_model_delta" in failed:
            recommendations.append(
                "Keep raw model deltas, provider routes, schema JSON, commands, and stdout in Inspector; main should show user task progress."
            )
        if not user_progress_events:
            recommendations.append(
                "Run real runtime tasks that persist user_progress.jsonl before treating Studio as an agent workspace."
            )
        if "process_kind_coverage" in failed:
            recommendations.append(
                "Cover plan, tool_use, tool_result, file_change, verification, and final transcript kinds so Studio can render the main session without event-name mapping."
            )
        if "inspector_model_delta_boundary" in failed:
            recommendations.append(
                "Mark runtime model delta user_progress events as display_level=inspector and emit a separate user-facing summary when needed."
            )
        if self._manifest_tasks(manifest) and not self.run_id:
            recommendations.append(
                "Execute at least the travel, small-code-change, log-analysis, document, and resume tasks before inviting a real inner-circle user."
            )
        return recommendations

    @staticmethod
    def _required_user_progress_kinds(manifest: dict[str, Any]) -> set[str]:
        raw = manifest.get("required_user_progress_kinds")
        if isinstance(raw, list):
            kinds = {str(item) for item in raw if str(item)}
            if kinds:
                return kinds
        return set(DEFAULT_REQUIRED_USER_PROGRESS_KINDS)

    def _task_coverage(self, tasks: list[dict[str, Any]]) -> int:
        sessions = self._load_sessions()
        covered = 0
        for task in tasks:
            goal = str(task.get("goal") or "").strip()
            required_events = {str(item) for item in task.get("required_events") or []}
            if not goal:
                continue
            for session in sessions:
                events = session["events"]
                if not any(
                    event.get("type") == "user_message"
                    and goal in str(event.get("content_delta") or event.get("summary") or "")
                    for event in events
                ):
                    continue
                event_types = {str(event.get("type")) for event in events}
                if required_events.issubset(event_types):
                    covered += 1
                    break
        return covered

    @staticmethod
    def _check(name: str, ok: bool, summary: str) -> dict[str, Any]:
        return {"name": name, "ok": ok, "summary": summary}

    @staticmethod
    def _raw_main_leaks(
        events: list[dict[str, Any]],
        user_progress_events: list[dict[str, Any]],
    ) -> list[str]:
        leaks: list[str] = []
        for event in events:
            event_type = str(event.get("type") or "")
            if event.get("display_level") == "inspector" or event_type == "user_message":
                continue
            if event_type in RAW_MAIN_EVENT_TYPES:
                leaks.append(event_type)
                continue
            text = StudioBenchmarkCommand._event_text(event)
            matched = next((pattern for pattern in RAW_MAIN_PATTERNS if pattern in text.lower()), "")
            if matched:
                leaks.append(matched)
        for event in user_progress_events:
            if event.get("display_level") == "inspector":
                continue
            if event.get("channel") == "model" and event.get("event_type") == "delta":
                leaks.append("user_progress:model_delta")
                continue
            text = StudioBenchmarkCommand._event_text(event)
            matched = next((pattern for pattern in RAW_MAIN_PATTERNS if pattern in text.lower()), "")
            if matched:
                leaks.append(f"user_progress:{matched}")
        return sorted(set(leaks))

    @staticmethod
    def _event_text(event: dict[str, Any]) -> str:
        return "\n".join(
            str(event.get(key) or "")
            for key in ("title", "summary", "content_delta")
        )

    @staticmethod
    def _is_user_facing_final(event: dict[str, Any]) -> bool:
        text = str(event.get("content_delta") or event.get("summary") or "").strip()
        if len(text) < 24:
            return False
        normalized = text.lower().lstrip()
        bad_prefixes = (
            "{",
            "[",
            "## 工作过程",
            "## process",
            "# final report",
            "final report",
            "executed run:",
            "created plan run",
            "runtime stdout",
        )
        if normalized.startswith(bad_prefixes):
            return False
        if not (
            normalized.startswith("## 答案")
            or normalized.startswith("## 结果")
            or normalized.startswith("答案")
            or normalized.startswith("结果")
        ):
            return False
        path_markers = text.count(".json") + text.count(".jsonl") + text.count("\\") + text.count("/")
        return path_markers <= 8

    @staticmethod
    def _manifest_tasks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        raw_tasks = manifest.get("tasks")
        if not isinstance(raw_tasks, list):
            return []
        return [task for task in raw_tasks if isinstance(task, dict)]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return events
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events
