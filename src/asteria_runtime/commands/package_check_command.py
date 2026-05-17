from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime import __version__


@dataclass(frozen=True)
class PackageCheck:
    name: str
    ok: bool
    summary: str
    severity: str = "error"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class PackageCheckResult:
    root: Path
    checks: list[PackageCheck] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(check.severity == "error" and not check.ok for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        failed = [check.name for check in self.checks if not check.ok]
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "ok": self.ok,
            "status": "pass" if self.ok else "fail",
            "summary": (
                "Package preflight checks passed."
                if self.ok
                else "Package preflight checks found blocking issues."
            ),
            "checks": [check.to_dict() for check in self.checks],
            "failed_checks": failed,
            "artifacts": self.artifacts,
            "next_actions": self._next_actions(failed),
        }

    def _next_actions(self, failed: list[str]) -> list[str]:
        actions: list[str] = []
        if failed:
            actions.append("Fix package metadata and version checks before building a gray package.")
        if "gray_route_template" in failed:
            actions.append("Add `templates/model.routes.gray.example.ps1` before gray rollout.")
        if "gray_command_modules" in failed:
            actions.append("Package real-model gate and acceptance modules before gray rollout.")
        if not self.artifacts:
            actions.append("Build a local wheel with `python -m build` when the build dependency is available.")
        actions.append("Configure model routes from `templates/model.routes.gray.example.ps1` in the target shell.")
        actions.append("Run `asteria version --json` from the installed package before gray rollout.")
        return actions

    def to_text(self) -> str:
        lines = [
            "Package check",
            f"Root: {self.root}",
            f"Status: {'pass' if self.ok else 'fail'}",
            "Checks:",
        ]
        for check in self.checks:
            marker = "ok" if check.ok else check.severity
            lines.append(f"  - {check.name}: {marker} - {check.summary}")
        if self.artifacts:
            lines.append("Artifacts:")
            lines.extend(f"  - {artifact}" for artifact in self.artifacts)
        else:
            lines.append("Artifacts: none")
        lines.append("Next actions:")
        lines.extend(f"  - {action}" for action in self._next_actions([] if self.ok else ["failed"]))
        return "\n".join(lines)


class PackageCheckCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> PackageCheckResult:
        pyproject = self._read_pyproject()
        checks = [
            self._pyproject_check(pyproject),
            self._build_backend_check(pyproject),
            self._console_script_check(pyproject),
            self._version_sync_check(pyproject),
            self._gray_command_modules_check(),
            self._route_template_check(),
            self._runbook_docs_check(),
        ]
        return PackageCheckResult(
            root=self.root,
            checks=checks,
            artifacts=self._dist_artifacts(),
        )

    def _read_pyproject(self) -> dict:
        path = self.root / "pyproject.toml"
        if not path.exists():
            return {}
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    def _pyproject_check(self, pyproject: dict) -> PackageCheck:
        project = pyproject.get("project") if isinstance(pyproject, dict) else None
        if not isinstance(project, dict):
            return PackageCheck("pyproject", False, "missing [project] metadata")
        name = project.get("name")
        version = project.get("version")
        ok = name == "asteria-runtime" and bool(version)
        return PackageCheck(
            "pyproject",
            ok,
            f"name={name or 'missing'}, version={version or 'missing'}",
        )

    def _build_backend_check(self, pyproject: dict) -> PackageCheck:
        build = pyproject.get("build-system") if isinstance(pyproject, dict) else None
        backend = build.get("build-backend") if isinstance(build, dict) else None
        ok = backend == "setuptools.build_meta"
        return PackageCheck(
            "build_backend",
            ok,
            f"build-backend={backend or 'missing'}",
        )

    def _console_script_check(self, pyproject: dict) -> PackageCheck:
        project = pyproject.get("project") if isinstance(pyproject, dict) else None
        scripts = project.get("scripts") if isinstance(project, dict) else None
        target = scripts.get("asteria") if isinstance(scripts, dict) else None
        ok = target == "asteria_runtime.cli:main"
        return PackageCheck(
            "console_script",
            ok,
            f"asteria={target or 'missing'}",
        )

    def _version_sync_check(self, pyproject: dict) -> PackageCheck:
        project = pyproject.get("project") if isinstance(pyproject, dict) else None
        package_version = project.get("version") if isinstance(project, dict) else None
        ok = package_version == __version__
        return PackageCheck(
            "version_sync",
            ok,
            f"pyproject={package_version or 'missing'}, runtime={__version__}",
        )

    def _gray_command_modules_check(self) -> PackageCheck:
        required = [
            "src/asteria_runtime/real_model_smoke.py",
            "src/asteria_runtime/real_model_gate.py",
            "src/asteria_runtime/real_model_acceptance.py",
        ]
        missing = [item for item in required if not (self.root / item).exists()]
        return PackageCheck(
            "gray_command_modules",
            not missing,
            (
                "real-model smoke/gate/acceptance package modules present"
                if not missing
                else "missing: " + ", ".join(missing)
            ),
        )

    def _route_template_check(self) -> PackageCheck:
        path = self.root / "templates" / "model.routes.gray.example.ps1"
        return PackageCheck(
            "gray_route_template",
            path.exists(),
            str(path.relative_to(self.root)) if path.exists() else "missing gray route template",
        )

    def _runbook_docs_check(self) -> PackageCheck:
        required = [
            "docs/zh/开发指南.md",
            "docs/zh/运行命令.md",
            "docs/zh/真实模型验收.md",
            "docs/zh/交付计划.md",
        ]
        missing = [item for item in required if not (self.root / item).exists()]
        return PackageCheck(
            "gray_docs",
            not missing,
            "gray rollout docs present" if not missing else "missing: " + ", ".join(missing),
        )

    def _dist_artifacts(self) -> list[str]:
        dist = self.root / "dist"
        if not dist.exists():
            return []
        artifacts = [
            str(path.relative_to(self.root))
            for path in sorted(dist.iterdir())
            if path.suffix in {".whl", ".gz", ".zip"}
        ]
        return artifacts
