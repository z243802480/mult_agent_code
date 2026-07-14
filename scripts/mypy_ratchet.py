"""Type-debt ratchet: block NEW mypy errors without pretending the old ones aren't there.

Why this exists: `mypy src` had 86 pre-existing errors and nobody saw them, because CI was switched
off at the repo level for six weeks (see the S77 notes). Turning mypy into a blocking gate on day one
would have meant either a multi-day cleanup before anything else could land, or — much worse —
quietly dropping mypy from the gate and calling CI "green".

So: the current errors are recorded in an explicit baseline file that is checked in and easy to read.
CI fails on any error that is NOT in that baseline. The debt is visible, it cannot grow, and it can be
paid down file by file.

Matching ignores line numbers (they shift with every unrelated edit) and keys on
(file, error code, message) with a count, so re-introducing the same error in the same file a SECOND
time is still caught.

Usage:
    python scripts/mypy_ratchet.py            # check; exit 1 on new errors
    python scripts/mypy_ratchet.py --update   # rewrite the baseline from the current state
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "mypy_baseline.json"
TARGET = "src"

# "path\to\file.py:123: error: message here  [code]"
ERROR_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+): error: (?P<message>.*?)\s+\[(?P<code>[a-z-]+)\]$")


def _run_mypy() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "mypy", TARGET],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1):  # 2+ means mypy itself failed (bad config, crash)
        sys.stderr.write(completed.stdout + completed.stderr)
        raise SystemExit(f"mypy could not run (exit {completed.returncode})")
    return completed.stdout


def _parse(output: str) -> Counter[tuple[str, str, str]]:
    found: Counter[tuple[str, str, str]] = Counter()
    for raw in output.splitlines():
        match = ERROR_RE.match(raw.strip())
        if not match:
            continue
        # Normalise the path so a baseline recorded on Windows matches a CI run on Linux.
        file = match.group("file").replace("\\", "/")
        found[(file, match.group("code"), match.group("message"))] += 1
    return found


def _load_baseline() -> Counter[tuple[str, str, str]]:
    if not BASELINE_PATH.exists():
        return Counter()
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return Counter(
        {
            (entry["file"], entry["code"], entry["message"]): entry["count"]
            for entry in data["errors"]
        }
    )


def _write_baseline(found: Counter[tuple[str, str, str]]) -> None:
    errors = [
        {"file": file, "code": code, "message": message, "count": count}
        for (file, code, message), count in sorted(found.items())
    ]
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "Pre-existing mypy errors, frozen so CI can block NEW ones. This is debt to pay "
                    "down, not a config to grow: only ever let this file shrink. Regenerate with "
                    "`python scripts/mypy_ratchet.py --update` after FIXING errors."
                ),
                "total": sum(found.values()),
                "errors": errors,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline from mypy's current output")
    args = parser.parse_args()

    found = _parse(_run_mypy())

    if args.update:
        _write_baseline(found)
        print(f"mypy baseline updated: {sum(found.values())} error(s) recorded in {BASELINE_PATH.name}")
        return 0

    baseline = _load_baseline()
    new_errors = found - baseline  # Counter subtraction: only counts above the baseline survive.
    fixed = baseline - found

    if fixed:
        print(f"mypy ratchet: {sum(fixed.values())} baseline error(s) no longer reported — nice.")
        print("             run `python scripts/mypy_ratchet.py --update` to tighten the baseline.")

    if not new_errors:
        print(f"mypy ratchet: OK — no new type errors ({sum(found.values())} known, tracked in {BASELINE_PATH.name}).")
        return 0

    print(f"mypy ratchet: {sum(new_errors.values())} NEW type error(s):\n")
    for (file, code, message), count in sorted(new_errors.items()):
        for _ in range(count):
            print(f"  {file}: {message}  [{code}]")
    print("\nFix them, or — if the change is deliberate — explain why in review. Do NOT add them to")
    print("the baseline: the baseline is only allowed to shrink.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
