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

# The two copies are now IDENTICAL and must stay that way. There used to be a
# KNOWN_SCHEMA_CONTENT_DRIFT allowlist here holding 17 pre-existing divergences; they were merged
# (union of properties/enums/required, verified by the full suite) and the allowlist is gone, so
# drift is now caught unconditionally. Do not reintroduce an allowlist — fix the drift instead:
# `python scripts/sync_schemas.py` copies the repo-root copy into the package.


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
    """Same-named root/packaged schemas must define the SAME contract — no exceptions.

    A source run validates against the repo-root copy; an installed wheel validates against the
    packaged one. When they diverge, the same runtime object is legal in one deployment and rejected
    in the other — and it fails only in the wheel, i.e. only for real users. The drift found in B7
    was exactly that: the packaged agent_run_graph REQUIRED three fields the root copy did not, so
    records written happily in dev would have been rejected once installed.
    """
    shared = _schema_names(ROOT_SCHEMAS) & _schema_names(PACKAGE_SCHEMAS)
    drifted = sorted(
        name for name in shared if _load(ROOT_SCHEMAS / name) != _load(PACKAGE_SCHEMAS / name)
    )
    assert not drifted, (
        "repo-root and packaged schema copies diverged in content — a source run and an installed "
        f"wheel would validate against different contracts: {drifted}. "
        "Run `python scripts/sync_schemas.py` (and make sure producers satisfy the merged copy)."
    )


def test_no_schema_is_packaged_without_a_repo_root_copy() -> None:
    """The mirror of test_every_repo_schema_is_packaged: a schema that exists ONLY in the package is
    invisible to source runs and to this repo's own review, and nothing keeps it honest."""
    orphaned = sorted(_schema_names(PACKAGE_SCHEMAS) - _schema_names(ROOT_SCHEMAS))
    assert not orphaned, (
        "schemas present only in the packaged copy (source runs never load these, so they drift "
        f"unreviewed): {orphaned}"
    )
