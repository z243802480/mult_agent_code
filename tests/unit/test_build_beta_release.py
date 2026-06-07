from __future__ import annotations

from pathlib import Path

from scripts.build_beta_release import _beta_install_readme, _read_version


def test_read_version_from_package() -> None:
    root = Path(__file__).resolve().parents[2]
    assert _read_version(root) == "0.1.0"


def test_beta_install_readme_mentions_release_zip() -> None:
    text = _beta_install_readme("0.1.0")
    assert "asteria-beta-0.1.0.zip" in text
    assert "install.ps1" in text
