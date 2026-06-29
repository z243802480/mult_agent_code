"""Guard against schema-packaging drift.

The runtime resolves schemas from the packaged ``asteria_runtime/schemas``
directory when installed from a wheel (see ``storage/schema_validator.py``),
but tests and source runs use the repo-root ``schemas/`` directory. If a schema
exists at the repo root but is missing from the package directory, every
installed-wheel command that validates it crashes with ``Schema not found``
(e.g. ``run_config.schema.json`` broke ``asteria goal`` from the wheel).

This test fails fast when the two diverge so the gap is caught before release.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_SCHEMAS = REPO_ROOT / "schemas"
PACKAGE_SCHEMAS = REPO_ROOT / "src" / "asteria_runtime" / "schemas"

# Same-named schemas whose repo-root and packaged copies currently differ in CONTENT.
# The runtime resolves the repo-root copy first (resources.schema_dir), so drift here means a
# source run and an installed wheel validate against different contracts — and the stale copy can
# silently under-validate persisted runtime objects (the user_progress_event drift let bogus
# transcript_kind values through until it was synced in S74). These entries are KNOWN pre-existing
# drift pending per-schema triage: decide the correct copy, verify producers satisfy the stricter
# one, then sync and REMOVE from this list. Do NOT add new names here — fix the drift instead.
KNOWN_SCHEMA_CONTENT_DRIFT = {
    "agent_loop_run_summary.schema.json",
    "agent_run_graph.schema.json",
    "context_budget_snapshot.schema.json",
    "context_mount.schema.json",
    "cost_report.schema.json",
    "daily_plan.schema.json",
    "daily_report.schema.json",
    "eval_report.schema.json",
    "goal_spec.schema.json",
    "model_call.schema.json",
    "model_capability_profile.schema.json",
    "model_route_check.schema.json",
    "runtime_profile.schema.json",
    "runtime_request.schema.json",
    "task.schema.json",
    "tool_observation.schema.json",
    "usage_signal_analysis.schema.json",
    "validation_run.schema.json",
}


def _schema_names(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.schema.json")}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_repo_schema_is_packaged() -> None:
    root = _schema_names(ROOT_SCHEMAS)
    packaged = _schema_names(PACKAGE_SCHEMAS)
    missing = sorted(root - packaged)
    assert not missing, (
        "schemas present at repo root but missing from the packaged "
        "asteria_runtime/schemas (would crash installed-wheel commands): "
        f"{missing}"
    )


def test_shared_schemas_have_identical_content() -> None:
    """Same-named root/packaged schemas must define the same contract.

    The runtime loads the repo-root copy; if it diverges from the packaged copy, source runs and
    installed wheels validate against different contracts and the stale copy can under-validate.
    KNOWN_SCHEMA_CONTENT_DRIFT carries the pre-existing drift pending per-schema triage.
    """
    shared = _schema_names(ROOT_SCHEMAS) & _schema_names(PACKAGE_SCHEMAS)
    drifted = sorted(
        name
        for name in shared
        if name not in KNOWN_SCHEMA_CONTENT_DRIFT
        and _load(ROOT_SCHEMAS / name) != _load(PACKAGE_SCHEMAS / name)
    )
    assert not drifted, (
        "repo-root and packaged schema copies diverged in content (runtime loads the root copy, so "
        "this validates source runs vs installed wheels against different contracts): "
        f"{drifted}. Sync them and verify producers satisfy the stricter copy."
    )


def test_known_schema_drift_allowlist_is_not_stale() -> None:
    """Allowlisted names must STILL drift; once synced, prune them so regressions are caught."""
    shared = _schema_names(ROOT_SCHEMAS) & _schema_names(PACKAGE_SCHEMAS)
    no_longer_drifting = sorted(
        name
        for name in KNOWN_SCHEMA_CONTENT_DRIFT
        if name in shared and _load(ROOT_SCHEMAS / name) == _load(PACKAGE_SCHEMAS / name)
    )
    assert not no_longer_drifting, (
        "these schemas no longer drift between root and packaged; remove them from "
        f"KNOWN_SCHEMA_CONTENT_DRIFT so future drift is caught: {no_longer_drifting}"
    )
