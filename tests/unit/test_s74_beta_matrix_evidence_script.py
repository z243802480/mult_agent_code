from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_beta_matrix_defaults_to_evidence_only(tmp_path: Path) -> None:
    output = tmp_path / "matrix.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/s74_beta_matrix_evidence.py",
            "--root",
            ".",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "evidence_only"
    assert report["complete"] is False
    assert report["ok"] is False
    assert report["slots"]
    assert all(item["status"] == "skipped" for item in report["slots"])
    assert all("--live" in item["skip_reason"] for item in report["slots"])
