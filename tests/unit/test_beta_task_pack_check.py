from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_beta_task_pack_check_passes_for_repo() -> None:
    root = Path(".").resolve()
    completed = subprocess.run(
        [sys.executable, "scripts/beta_task_pack_check.py", "--root", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    assert "small_code_change" in report["task_ids"]
    labels = {item["label"] for item in report["checks"]}
    assert "trial template captures session experience" in labels
    assert "trial template enforces external evidence boundary" in labels
    assert "maintainer invitation has release preflight" in labels
