from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_MAIN_EVENTS = {
    "user_message",
    "assistant_delta",
    "reasoning_delta",
    "model_start",
    "model_delta",
    "final_answer",
    "permission_request",
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
        }

    def to_text(self) -> str:
        status = "ready" if self.ok else "not_ready"
        lines = [
            f"Studio benchmark: {status}",
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
    ) -> None:
        self.root = root
        self.manifest = manifest or root / "benchmarks" / "studio_user_tasks.json"
        self.session_id = session_id

    def run(self) -> StudioBenchmarkResult:
        manifest = self._read_json(self.manifest)
        sessions = self._load_sessions()
        events = [event for session in sessions for event in session["events"]]
        user_progress_events = self._load_user_progress_events()
        checks = self._evaluate(events, user_progress_events, manifest)
        score = round(sum(1 for check in checks if check["ok"]) / max(1, len(checks)), 4)
        threshold = float(manifest.get("minimum_ready_score", 0.8))
        recommendations = self._recommendations(checks, sessions, user_progress_events, manifest)
        blocking_failures = {
            check["name"]
            for check in checks
            if not check["ok"] and check["name"] in {"session_activity", "benchmark_task_coverage"}
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
        progress_channels = {str(event.get("channel")) for event in user_progress_events}
        required_channels = self._required_user_progress_channels(manifest)
        main_events = [
            event
            for event in events
            if event.get("display_level") != "inspector"
            and str(event.get("type")) in DEFAULT_REQUIRED_MAIN_EVENTS
        ]
        inspector_events = [event for event in events if event.get("display_level") == "inspector"]
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
                bool({"reasoning_delta", "model_start", "model_delta"} & event_types),
                "Planning/model progress is visible."
                if {"reasoning_delta", "model_start", "model_delta"} & event_types
                else "No planning or model progress event found.",
            ),
            self._check(
                "permission_or_result",
                bool({"permission_request", "final_answer", "model_delta"} & event_types),
                "The task reaches a permission, model, or final result surface."
                if {"permission_request", "final_answer", "model_delta"} & event_types
                else "No permission, model, or final result event found.",
            ),
            self._check(
                "inspector_separation",
                bool(inspector_events) or not any(str(event.get("type", "")).startswith("tool_") for event in main_events),
                "Tool/runtime details are separated from the main user thread."
                if bool(inspector_events) or not any(str(event.get("type", "")).startswith("tool_") for event in main_events)
                else "Tool/runtime details leak into the main user thread.",
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
                "process_channel_coverage",
                required_channels.issubset(progress_channels),
                f"Covered user progress channels: {', '.join(sorted(progress_channels & required_channels))}."
                if progress_channels & required_channels
                else f"No required user progress channels covered: {', '.join(sorted(required_channels))}.",
            ),
        ]
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
        if not sessions:
            recommendations.append(
                "Run the Studio benchmark tasks through the UI and preserve session events."
            )
        if "task_progress" in failed:
            recommendations.append(
                "Expose runtime-native user progress events before adding more UI panels."
            )
        if "permission_or_result" in failed:
            recommendations.append(
                "Make every task reach either a permission card, model response, or final answer."
            )
        if "inspector_separation" in failed:
            recommendations.append(
                "Keep raw commands/stdout in Inspector and show user-facing progress in the thread."
            )
        if not user_progress_events:
            recommendations.append(
                "Run real runtime tasks that persist user_progress.jsonl before treating Studio as an agent workspace."
            )
        if "process_channel_coverage" in failed:
            recommendations.append(
                "Cover model, tool, file, and evidence channels so Studio can show thinking, shell, diffs, and artifacts without guessing."
            )
        if self._manifest_tasks(manifest):
            recommendations.append(
                "Execute at least the travel, small-code-change, log-analysis, document, and resume tasks before inviting a real inner-circle user."
            )
        return recommendations

    @staticmethod
    def _required_user_progress_channels(manifest: dict[str, Any]) -> set[str]:
        raw = manifest.get("required_user_progress_channels")
        if isinstance(raw, list):
            channels = {str(item) for item in raw if str(item)}
            if channels:
                return channels
        return {"model", "tool", "file", "evidence"}

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
