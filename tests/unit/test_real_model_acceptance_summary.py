from __future__ import annotations

import argparse
from pathlib import Path

from asteria_runtime.real_model_acceptance import summary_output_paths


def test_full_suite_writes_canonical_acceptance_summary(tmp_path: Path) -> None:
    args = argparse.Namespace(
        suite="readiness",
        scenario=[],
        summary_json=tmp_path / "custom_readiness.json",
    )

    paths = summary_output_paths(args, tmp_path)

    assert paths == [
        (tmp_path / "custom_readiness.json").resolve(),
        tmp_path / ".asteria" / "verification" / "real_model_acceptance_readiness.json",
    ]


def test_scenario_subset_does_not_overwrite_canonical_summary(tmp_path: Path) -> None:
    args = argparse.Namespace(
        suite="readiness",
        scenario=["readiness_refactor"],
        summary_json=tmp_path / "readiness_refactor.json",
    )

    paths = summary_output_paths(args, tmp_path)

    assert paths == [(tmp_path / "readiness_refactor.json").resolve()]


def test_default_full_suite_summary_is_canonical(tmp_path: Path) -> None:
    args = argparse.Namespace(
        suite="core",
        scenario=[],
        summary_json=None,
    )

    paths = summary_output_paths(args, tmp_path)

    assert paths == [
        tmp_path / ".asteria" / "verification" / "real_model_acceptance_core.json"
    ]
