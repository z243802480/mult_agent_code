from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AcceptanceHistoryResult:
    history_path: Path
    entries: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        if not self.entries:
            return f"Acceptance history: none\nExpected: {self.history_path}"
        lines = [
            "Acceptance history",
            f"Path: {self.history_path}",
            f"Entries: {len(self.entries)}",
        ]
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        for entry in self.entries:
            aggregate = self._dict(entry.get("aggregate"))
            trend = self._dict(entry.get("trend"))
            deltas = self._dict(trend.get("deltas"))
            failed = aggregate.get("failed", 0)
            status = "pass" if entry.get("ok") else "fail"
            lines.append(
                (
                    f"- {entry.get('created_at') or 'unknown'} "
                    f"{entry.get('suite') or 'unknown'} [{status}] "
                    f"{aggregate.get('passed', 0)}/{aggregate.get('total', 0)} passed, "
                    f"failed={failed}, "
                    f"model={aggregate.get('model_calls', 0)}, "
                    f"tool={aggregate.get('tool_calls', 0)}, "
                    f"duration={aggregate.get('duration_seconds', 0)}s"
                )
            )
            delta_line = self._delta_line(deltas)
            if delta_line:
                lines.append(f"  delta: {delta_line}")
            failed_scenarios = aggregate.get("failed_scenarios") or []
            if failed_scenarios:
                lines.append(f"  failed scenarios: {', '.join(str(item) for item in failed_scenarios)}")
        return "\n".join(lines)

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _delta_line(self, deltas: dict[str, Any]) -> str:
        if not deltas:
            return ""
        keys = [
            "failed",
            "duration_seconds",
            "model_calls",
            "tool_calls",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "repair_attempts",
        ]
        parts = []
        for key in keys:
            if key in deltas:
                parts.append(f"{key}={self._format_delta(deltas[key])}")
        return ", ".join(parts)

    def _format_delta(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        sign = "+" if number > 0 else ""
        if number.is_integer():
            return f"{sign}{int(number)}"
        return f"{sign}{number:.3f}".rstrip("0").rstrip(".")


class AcceptanceHistoryCommand:
    def __init__(
        self,
        root: Path,
        limit: int = 10,
        suite: str | None = None,
        history_jsonl: Path | None = None,
        warn_model_call_delta: int = 5,
        warn_duration_delta: float = 120.0,
        warn_repair_delta: int = 1,
        warn_context_compaction_delta: int = 1,
    ) -> None:
        self.root = root.resolve()
        self.limit = limit
        self.suite = suite
        self.history_jsonl = history_jsonl
        self.warn_model_call_delta = warn_model_call_delta
        self.warn_duration_delta = warn_duration_delta
        self.warn_repair_delta = warn_repair_delta
        self.warn_context_compaction_delta = warn_context_compaction_delta

    def run(self) -> AcceptanceHistoryResult:
        history_path = self.history_jsonl or self.root / ".agent" / "acceptance" / "history.jsonl"
        entries = self._read_history(history_path)
        if self.suite:
            entries = [entry for entry in entries if entry.get("suite") == self.suite]
        if self.limit > 0:
            entries = entries[-self.limit :]
        return AcceptanceHistoryResult(history_path, entries, self._warnings(entries))

    def _read_history(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _warnings(self, entries: list[dict[str, Any]]) -> list[str]:
        if not entries:
            return []
        latest = entries[-1]
        aggregate = self._dict(latest.get("aggregate"))
        trend = self._dict(latest.get("trend"))
        deltas = self._dict(trend.get("deltas"))
        warnings = []
        failed = self._number(aggregate.get("failed"))
        if failed > 0:
            warnings.append(f"latest run has {int(failed)} failed scenario(s)")
        failed_delta = self._number(deltas.get("failed"))
        if failed_delta > 0:
            warnings.append(f"failed scenario count increased by {self._format_number(failed_delta)}")
        model_delta = self._number(deltas.get("model_calls"))
        if model_delta >= self.warn_model_call_delta:
            warnings.append(
                f"model calls increased by {self._format_number(model_delta)} "
                f"(threshold {self.warn_model_call_delta})"
            )
        duration_delta = self._number(deltas.get("duration_seconds"))
        if duration_delta >= self.warn_duration_delta:
            warnings.append(
                f"duration increased by {self._format_number(duration_delta)}s "
                f"(threshold {self._format_number(self.warn_duration_delta)}s)"
            )
        repair_delta = self._number(deltas.get("repair_attempts"))
        if repair_delta >= self.warn_repair_delta:
            warnings.append(
                f"repair attempts increased by {self._format_number(repair_delta)} "
                f"(threshold {self.warn_repair_delta})"
            )
        compaction_delta = self._number(deltas.get("context_compactions"))
        if compaction_delta >= self.warn_context_compaction_delta:
            warnings.append(
                f"context compactions increased by {self._format_number(compaction_delta)} "
                f"(threshold {self.warn_context_compaction_delta})"
            )
        return warnings

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _number(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _format_number(self, value: float) -> str:
        if value.is_integer():
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".")
