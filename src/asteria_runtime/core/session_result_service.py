from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.storage.schema_validator import SchemaValidator


class SessionResultService:
    """Single public entry point for persisted session results and continuation memory."""

    def __init__(self, root: Path, validator: SchemaValidator | None = None) -> None:
        self.root = root.resolve()
        self.validator = validator or SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def latest_review_status(self, run_id: str) -> str:
        from asteria_runtime.storage.json_store import JsonStore

        path = self.root / ".asteria" / "runs" / run_id / "eval_report.json"
        if not path.exists():
            return "unknown"
        report = JsonStore(self.validator).read(path, "eval_report")
        return str(report["overall"]["status"])

    def write_final_report(self, run_id: str, review_status: str, steps: list[Any]) -> Path:
        return self._report_backend()._write_final_report(run_id, review_status, steps)

    def write_final_report_summary(
        self,
        *,
        run_id: str,
        status: str,
        review_status: str,
        final_report_path: Path,
        status_payload: dict[str, Any],
    ) -> Path:
        return self._report_backend()._write_final_report_summary(
            run_id=run_id,
            status=status,
            review_status=review_status,
            final_report_path=final_report_path,
            status_payload=status_payload,
        )

    def write_run_loop_summary(
        self,
        *,
        run_id: str,
        steps: list[Any],
        status_payload: dict[str, Any],
        stop_reason: str,
    ) -> Path:
        return self._report_backend()._write_run_loop_summary(
            run_id=run_id,
            steps=steps,
            status_payload=status_payload,
            stop_reason=stop_reason,
        )

    def write_active_goal_memory(
        self,
        *,
        run_id: str,
        review_status: str,
        **kwargs: Any,
    ) -> Path | None:
        return self._report_backend()._write_active_goal_memory(
            run_id=run_id,
            review_status=review_status,
            **kwargs,
        )

    def _report_backend(self) -> Any:
        # Report rendering is retained as a compatibility backend while all product
        # commands depend on this service boundary rather than on one another.
        from asteria_runtime.commands.run_command import RunCommand

        return RunCommand(self.root)
