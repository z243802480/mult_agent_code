import json
import shutil
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand
from asteria_runtime.core.user_progress_view import required_main_transcript_kinds

pytestmark = pytest.mark.workflow

GOLDEN_RUN_ID = "s7-golden-run"
FIXTURE_ROOT = Path("benchmarks/fixtures/s7_golden_run")


def _install_golden_run(workspace: Path) -> None:
    run_dir = workspace / ".asteria" / "runs" / GOLDEN_RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE_ROOT / "user_progress.jsonl", run_dir / "user_progress.jsonl")


def test_s7_golden_run_passes_run_scoped_studio_benchmark(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _install_golden_run(tmp_path)

    manifest = Path("benchmarks/studio_user_tasks.json")
    gate = json.loads(Path("benchmarks/phase2_mvp_gate.json").read_text(encoding="utf-8"))
    result = StudioBenchmarkCommand(
        tmp_path,
        manifest=manifest,
        run_id=GOLDEN_RUN_ID,
    ).run()
    checks = {check["name"]: check for check in result.checks}

    assert result.to_dict()["scope"] == f"run:{GOLDEN_RUN_ID}"
    assert result.score >= float(gate["score_threshold"])
    assert result.ok is True
    assert checks["process_kind_coverage"]["ok"] is True
    assert checks["main_thread_no_raw_model_delta"]["ok"] is True

    events = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "runs" / GOLDEN_RUN_ID / "user_progress.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    required_kinds = set(gate["required_user_progress_kinds"])
    assert required_kinds <= required_main_transcript_kinds(events)
