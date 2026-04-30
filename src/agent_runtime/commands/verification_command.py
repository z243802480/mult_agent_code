from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class VerificationStatusResult:
    summary_path: Path
    summary: dict | None

    def to_text(self) -> str:
        if self.summary is None:
            return f"Verification summary: none\nExpected: {self.summary_path}"
        lines = [
            "Verification summary",
            f"Status: {self.summary['status']}",
            f"Platform: {self.summary['platform']}",
            f"Created: {self.summary['created_at']}",
            f"Path: {self.summary_path}",
            "Checks:",
        ]
        lines.extend(
            f"  - {check['name']}: {check['status']} - {check['summary']}"
            for check in self.summary["checks"]
        )
        artifacts = self.summary.get("artifacts", {})
        if artifacts:
            lines.append("Artifacts:")
            for key in ("cli_workspace", "snapshot_count", "handoff_count"):
                if key in artifacts:
                    lines.append(f"  - {key}: {artifacts[key]}")
        return "\n".join(lines)


class VerificationStatusCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> VerificationStatusResult:
        summary_path = self.root / ".agent" / "verification" / "latest.json"
        if not summary_path.exists():
            return VerificationStatusResult(summary_path, None)
        return VerificationStatusResult(
            summary_path,
            self.store.read(summary_path, "verification_summary"),
        )
