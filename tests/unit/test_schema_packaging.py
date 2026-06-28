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

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_SCHEMAS = REPO_ROOT / "schemas"
PACKAGE_SCHEMAS = REPO_ROOT / "src" / "asteria_runtime" / "schemas"


def _schema_names(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.schema.json")}


def test_every_repo_schema_is_packaged() -> None:
    root = _schema_names(ROOT_SCHEMAS)
    packaged = _schema_names(PACKAGE_SCHEMAS)
    missing = sorted(root - packaged)
    assert not missing, (
        "schemas present at repo root but missing from the packaged "
        "asteria_runtime/schemas (would crash installed-wheel commands): "
        f"{missing}"
    )
