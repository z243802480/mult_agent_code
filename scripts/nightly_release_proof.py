"""Summarize *executed* keyed nightly steps, not just green workflow jobs.

GitHub marks a job successful when its keyed smoke step is skipped for missing secrets.
The release summary must not turn that job conclusion into a claim of model proof.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _classify_proof(
    run: dict, jobs: dict, *, job_name: str, step_name: str, label: str
) -> tuple[str, str]:
    if not run:
        return "NEVER RUN", "No nightly run exists on the default branch."
    if run.get("status") not in (None, "completed"):
        return "NOT GREEN", "The latest nightly is still running."
    if not jobs or not isinstance(jobs.get("jobs"), list):
        if label == "runtime ring-recovery" and run.get("conclusion") == "failure":
            return "FAILED", "The ring-recovery nightly failed, and its jobs could not be read."
        return "UNKNOWN", "Nightly jobs could not be read."
    job = next((item for item in jobs["jobs"] if item.get("name") == job_name), None)
    if job is None:
        return "NEVER RUN", f"The latest nightly predates the {label} proof job."
    smoke = next((step for step in job.get("steps", []) if step.get("name") == step_name), None)
    if smoke is None:
        if job.get("conclusion") == "failure":
            return "FAILED", f"The {label} job failed before its model step."
        return "UNKNOWN", f"The {label} model step is absent from the job record."
    if job.get("conclusion") == "failure":
        return "FAILED", f"The {label} job failed."
    if smoke.get("conclusion") == "skipped":
        return "NOT RUN", f"The keyed {label} model step was skipped; provider keys may be missing."
    if smoke.get("conclusion") == "success" and job.get("conclusion") == "success":
        return "PASSED", f"The keyed {label} model step completed successfully."
    if smoke.get("conclusion") == "failure" or job.get("conclusion") == "failure":
        return "FAILED", f"The {label} model step failed."
    return "NOT GREEN", f"The {label} model step concluded {smoke.get('conclusion') or 'unknown'}."


def classify_studio_proof(run: dict, jobs: dict) -> tuple[str, str]:
    """Return Studio proof status from its actual smoke step."""
    return _classify_proof(
        run,
        jobs,
        job_name="studio-real-model-nightly",
        step_name="Studio real-model smokes",
        label="Studio",
    )


def classify_ring_proof(run: dict, jobs: dict) -> tuple[str, str]:
    """Return runtime proof status from its actual ring-recovery step."""
    return _classify_proof(
        run,
        jobs,
        job_name="ring-recovery",
        step_name="Ring recovery (full RunCommand end-to-end, real stack)",
        label="runtime ring-recovery",
    )


def main() -> None:
    runs = json.loads(os.environ.get("RUN_JSON", "[]") or "[]")
    run = runs[0] if isinstance(runs, list) and runs else {}
    jobs = json.loads(os.environ.get("JOBS_JSON", "{}") or "{}")
    kind = os.environ.get("PROOF_KIND", "studio")
    if kind not in {"studio", "ring"}:
        raise ValueError(f"unknown proof kind: {kind}")
    if runs is None:
        status, detail = "UNKNOWN", "Nightly runs could not be read."
    else:
        status, detail = (
            classify_studio_proof(run, jobs) if kind == "studio" else classify_ring_proof(run, jobs)
        )
    url = str(run.get("url") or "")
    created = str(run.get("createdAt") or "")
    suffix = f" — [run]({url})" if url else ""
    when = f" at `{created}`" if created else ""
    title = "Studio real-model proof" if kind == "studio" else "Real-stack proof (ring-recovery)"
    summary = f"## {title}\n> **{status}**{when}{suffix}. {detail}\n"
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
        output.write(summary)
    if status != "PASSED":
        print(f"::notice::{title}: {status}. {detail}")
    if kind == "ring" and status == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
