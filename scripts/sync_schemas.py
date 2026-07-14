"""Sync the packaged schema copy from the repo-root one.

The runtime validates against ``schemas/`` when running from source and against the packaged
``src/asteria_runtime/schemas/`` when installed from a wheel. Two copies of the same contract is a
packaging fact we cannot remove (the wheel must carry its schemas), so the repo-root copy is the
SINGLE SOURCE OF TRUTH and this script mirrors it into the package.

Drift between them fails only in the wheel — that is, only for real users — which is why
``tests/unit/test_schema_packaging.py`` guards it unconditionally. When that test goes red, edit the
repo-root schema and run:

    python scripts/sync_schemas.py

``--check`` reports what would change without writing (the CI-friendly form).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SCHEMAS = REPO_ROOT / "schemas"
PACKAGE_SCHEMAS = REPO_ROOT / "src" / "asteria_runtime" / "schemas"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report differences without writing (exit 1 when out of sync)",
    )
    args = parser.parse_args()

    PACKAGE_SCHEMAS.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for source in sorted(ROOT_SCHEMAS.glob("*.schema.json")):
        target = PACKAGE_SCHEMAS / source.name
        if not target.exists() or target.read_bytes() != source.read_bytes():
            stale.append(source.name)
            if not args.check:
                shutil.copyfile(source, target)

    # A packaged schema with no repo-root counterpart is unreviewable — it can only have come from a
    # copy that was never brought back. Report it; deleting is a judgement call, not a sync.
    orphaned = sorted(
        path.name
        for path in PACKAGE_SCHEMAS.glob("*.schema.json")
        if not (ROOT_SCHEMAS / path.name).exists()
    )

    if args.check:
        if stale:
            print(f"out of sync ({len(stale)}): {', '.join(stale)}")
        if orphaned:
            print(f"packaged-only, no repo-root copy ({len(orphaned)}): {', '.join(orphaned)}")
        if not stale and not orphaned:
            print(f"schemas in sync ({len(list(ROOT_SCHEMAS.glob('*.schema.json')))} files).")
            return 0
        return 1

    print(f"synced {len(stale)} schema(s) into {PACKAGE_SCHEMAS.relative_to(REPO_ROOT)}.")
    if orphaned:
        print(f"WARNING packaged-only schemas (no repo-root copy): {', '.join(orphaned)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
