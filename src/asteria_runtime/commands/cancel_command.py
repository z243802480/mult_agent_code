"""Finalize a run whose worker process is gone.

`RunStateFinalizer` only revises a run record while the run's own process is alive. When the
process is stopped from outside (user Stop tree-kills it, crash, reboot) a run whose loop still
had work left stays `status: running` with `ended_at: null` forever — a zombie record that says a
dead run is still working. Routing stopped trusting that record in 1.2.151 (writer_process_alive);
this command repairs the RECORD itself, so every evidence consumer (status, review, accept, the
Studio header) sees the truth: the run was cancelled, it never finished.

Studio is a first-class CLIENT of runtime evidence (AGENTS §9), so the BFF does not write
run.json — it invokes this command after tree-killing the worker. The command refuses to mark a
run whose writer lock is still held: a held lock means the run is genuinely alive, and "cancel"
must never be how a live run gets declared dead. Because the kill and this command race (Windows
taskkill releases the lock a moment after it is issued), the command waits briefly for the lock to
drop before refusing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.workspace_writer_lock import writer_process_alive
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso

# The taskkill→lock-release race: after the BFF tree-kills the worker the OS can take a moment to
# release the writer lock. Wait briefly before concluding the run is genuinely alive.
LOCK_DROP_TIMEOUT_SECONDS = 6.0
LOCK_DROP_POLL_SECONDS = 0.5

SETTLED_STATUSES = {"completed", "failed", "cancelled", "paused", "blocked"}


@dataclass(frozen=True)
class CancelResult:
    run_id: str | None
    status: str  # "cancelled" | "already_settled" | "alive" | "not_found"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"cancelled", "already_settled"}


class CancelCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        validator: SchemaValidator | None = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.validator = validator or SchemaValidator(
            Path(__file__).resolve().parents[2] / "schemas"
        )

    def run(self) -> CancelResult:
        agent_dir = self.root / ".asteria"
        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            return CancelResult(None, "not_found", "No current run to cancel.")
        try:
            run = run_store.load_run(run_id)
        except FileNotFoundError:
            return CancelResult(run_id, "not_found", f"Run {run_id} does not exist.")
        if str(run.get("status")) in SETTLED_STATUSES:
            return CancelResult(
                run_id, "already_settled", f"Run {run_id} already settled as {run['status']}."
            )
        # A held writer lock means the run is genuinely alive — never declare a live run dead.
        # Wait out the kill→lock-release race first.
        deadline = time.monotonic() + LOCK_DROP_TIMEOUT_SECONDS
        while writer_process_alive(self.root):
            if time.monotonic() >= deadline:
                return CancelResult(
                    run_id,
                    "alive",
                    f"Run {run_id} is still holding the workspace writer lock — it looks alive, refusing to mark it cancelled.",
                )
            time.sleep(LOCK_DROP_POLL_SECONDS)
        run["status"] = "cancelled"
        run["ended_at"] = now_iso()
        run["summary"] = "Run cancelled by the user; the worker process was stopped before it could finalize."
        run_store.update_run(run)
        EventLogger(run_store.run_dir(run_id) / "events.jsonl", self.validator).record(
            run_id,
            "run_cancelled",
            "CancelCommand",
            "Run marked cancelled after its worker process was stopped.",
        )
        return CancelResult(run_id, "cancelled", f"Run {run_id} marked cancelled.")
