from __future__ import annotations

from pathlib import Path

from scripts.build_beta_release import _beta_install_readme, _read_version


def test_read_version_from_package() -> None:
    root = Path(__file__).resolve().parents[2]
    version = _read_version(root)
    assert version.startswith("0.2.")


def test_beta_install_readme_mentions_release_zip() -> None:
    root = Path(__file__).resolve().parents[2]
    version = _read_version(root)
    text = _beta_install_readme(version)
    assert f"asteria-beta-{version}.zip" in text
    assert "install.ps1" in text
