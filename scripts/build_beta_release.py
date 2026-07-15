"""Build GitHub Release assets: wheel, Studio bundle, and Beta install pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

STUDIO_RUNTIME_FILES = (
    "server.mjs",
    "intent-router.mjs",
    "prompt-contract.mjs",
)

BETA_DOC_PATHS = (
    "docs/zh/Beta-GitHub-Release安装.md",
    "docs/zh/Beta用户入门.md",
    "docs/zh/Beta试跑清单.md",
    "docs/zh/Beta内测邀请.md",
    "docs/zh/reports/S14-beta-user-trial-template.md",
)

TEMPLATE_PATHS = (
    "templates/model.routes.validation.example.ps1",
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build Beta GitHub Release assets.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--dist-dir", type=Path, default=None, help="Output directory")
    parser.add_argument("--skip-studio-build", action="store_true", help="Reuse studio/dist if present")
    args = parser.parse_args()

    root = args.root.resolve()
    dist_dir = (args.dist_dir or root / "dist").resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)

    version = _read_version(root)
    _build_wheel(root, dist_dir)
    wheel = _latest_wheel(dist_dir)
    studio_zip = _build_studio_bundle(root, dist_dir, version, skip_build=args.skip_studio_build)
    beta_zip = _build_beta_pack(root, dist_dir, version, wheel, studio_zip)
    checksums = _write_checksums(dist_dir, [wheel, studio_zip, beta_zip])

    report = {
        "ok": True,
        "version": version,
        "wheel": str(wheel),
        "studio_zip": str(studio_zip),
        "beta_pack": str(beta_zip),
        "checksums": str(checksums),
        "github_release_assets": [
            wheel.name,
            studio_zip.name,
            beta_zip.name,
            checksums.name,
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _read_version(root: Path) -> str:
    init_path = root / "src" / "asteria_runtime" / "__init__.py"
    for line in init_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("Could not read __version__ from asteria_runtime")


def _build_wheel(root: Path, dist_dir: Path) -> None:
    # Pass dist_dir through: without it build_package.py writes the wheel to its own default (root/dist)
    # while _latest_wheel(dist_dir) looks in the requested dir, so a custom --dist-dir found no wheel and
    # aborted the whole pack. Default runs (dist_dir == root/dist) are unchanged.
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "build_package.py"),
            "--root",
            str(root),
            "--dist-dir",
            str(dist_dir),
            "--clean",
            "--no-deps",
        ],
        check=True,
    )


def _latest_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("asteria_runtime-*.whl"))
    if not wheels:
        raise SystemExit(f"No wheel found in {dist_dir}")
    return max(wheels, key=lambda item: item.stat().st_mtime)


def _build_studio_bundle(root: Path, dist_dir: Path, version: str, *, skip_build: bool) -> Path:
    studio_dir = root / "studio"
    dist_ui = studio_dir / "dist"
    if not skip_build:
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit("npm is required to build Studio dist for release assets.")
        subprocess.run([npm, "run", "build"], cwd=studio_dir, check=True)
    if not (dist_ui / "index.html").is_file():
        raise SystemExit("studio/dist/index.html missing; run `cd studio && npm run build`.")

    staging = dist_dir / f"asteria-studio-{version}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in STUDIO_RUNTIME_FILES:
        shutil.copy2(studio_dir / name, staging / name)
    shutil.copytree(dist_ui, staging / "dist")

    zip_path = dist_dir / f"asteria-studio-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()
    _zip_directory(staging, zip_path)
    shutil.rmtree(staging)
    return zip_path


def _build_beta_pack(root: Path, dist_dir: Path, version: str, wheel: Path, studio_zip: Path) -> Path:
    pack_root = dist_dir / f"asteria-beta-{version}"
    if pack_root.exists():
        shutil.rmtree(pack_root)
    pack_root.mkdir(parents=True)

    wheels_dir = pack_root / "dist-packages"
    wheels_dir.mkdir()
    shutil.copy2(wheel, wheels_dir / wheel.name)

    studio_dir = pack_root / "studio"
    _extract_zip(studio_zip, studio_dir)

    templates_dir = pack_root / "templates"
    templates_dir.mkdir()
    for rel in TEMPLATE_PATHS:
        src = root / rel
        shutil.copy2(src, templates_dir / Path(rel).name)

    docs_dir = pack_root / "docs"
    docs_dir.mkdir()
    for rel in BETA_DOC_PATHS:
        src = root / rel
        shutil.copy2(src, docs_dir / Path(rel).name)

    shutil.copy2(root / "scripts" / "beta_install.ps1", pack_root / "install.ps1")
    shutil.copy2(root / "scripts" / "beta_install.sh", pack_root / "install.sh")
    (pack_root / "README-BETA-INSTALL.md").write_text(
        _beta_install_readme(version),
        encoding="utf-8",
    )

    zip_path = dist_dir / f"{pack_root.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    _zip_directory(pack_root, zip_path)
    shutil.rmtree(pack_root)
    return zip_path


def _beta_install_readme(version: str) -> str:
    return f"""# Asteria Beta {version} — 安装说明

无需 clone 源码。下载 **asteria-beta-{version}.zip** 后：

## Windows

```powershell
Expand-Archive .\\asteria-beta-{version}.zip -DestinationPath .\\asteria-beta
cd .\\asteria-beta
powershell -ExecutionPolicy Bypass -File .\\install.ps1
```

## macOS / Linux

```bash
unzip asteria-beta-{version}.zip -d asteria-beta
cd asteria-beta
bash install.sh
```

安装完成后：

```powershell
asteria init --root %USERPROFILE%\\asteria-workspace
asteria studio --root %USERPROFILE%\\asteria-workspace
```

详细步骤见包内 `docs/Beta用户入门.md` 与 `docs/Beta试跑清单.md`。
配置模型 Key 见 `templates/model.routes.validation.example.ps1`（复制到本机私有配置，勿提交 git）。
"""


def _zip_directory(source: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def _extract_zip(zip_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target)


def _write_checksums(dist_dir: Path, paths: list[Path]) -> Path:
    lines: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    out = dist_dir / "SHA256SUMS.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
