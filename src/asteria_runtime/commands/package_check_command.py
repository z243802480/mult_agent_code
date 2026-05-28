from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime import __version__
from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.core.error_taxonomy import classify_check, taxonomy_summary


@dataclass(frozen=True)
class PackageCheck:
    name: str
    ok: bool
    summary: str
    severity: str = "error"
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "severity": self.severity,
            "error_type": self.error_type or classify_check(self.name),
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
            "control_surface": control_surface_contract(
                command="package-check",
                audience="maintainer_preflight",
                stable_fields=[
                    "schema_version",
                    "root",
                    "ok",
                    "status",
                    "summary",
                    "checks",
                    "failed_checks",
                    "artifacts",
                    "runbook",
                    "error_taxonomy",
                    "next_actions",
                ],
            ),
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
            "runbook": self._runbook(),
            "error_taxonomy": taxonomy_summary(),
            "next_actions": self._next_actions(failed),
        }

    def _next_actions(self, failed: list[str]) -> list[str]:
        actions: list[str] = []
        if failed:
            actions.append("Fix package metadata and version checks before building a readiness package.")
        if "readiness_route_template" in failed:
            actions.append("Add `templates/model.routes.readiness.example.ps1` before readiness rollout.")
        if "readiness_command_modules" in failed:
            actions.append("Package real-model gate and acceptance modules before readiness rollout.")
        if "hook_plugin_control_surface" in failed:
            actions.append("Package hook/plugin schemas, command modules, defaults, and docs.")
        if "readiness_runbook" in failed:
            actions.append("Add `docs/zh/发布准备验证试运行手册.md` before readiness rollout.")
        if not self.artifacts:
            actions.append("Build a local wheel with `python -m build` when the build dependency is available.")
        actions.append("Follow `docs/zh/发布准备验证试运行手册.md` for install, route config, self-check, rollback, and failure collection.")
        actions.append("Configure model routes from `templates/model.routes.readiness.example.ps1` in the target shell.")
        actions.append("Run `asteria version --json` from the installed package before readiness rollout.")
        return actions

    def _runbook(self) -> dict[str, object]:
        return {
            "path": "docs/zh/发布准备验证试运行手册.md",
            "required_sections": [
                "install",
                "route_config",
                "self_check",
                "upgrade",
                "rollback",
                "failure_collection",
                "pause_resume",
            ],
        }

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
            self._readiness_command_modules_check(),
            self._hook_plugin_control_surface_check(),
            self._route_template_check(),
            self._runbook_docs_check(),
            self._readiness_runbook_check(),
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

    def _readiness_command_modules_check(self) -> PackageCheck:
        required = [
            "src/asteria_runtime/real_model_smoke.py",
            "src/asteria_runtime/real_model_gate.py",
            "src/asteria_runtime/real_model_acceptance.py",
            "src/asteria_runtime/commands/gate_command.py",
            "src/asteria_runtime/commands/readiness_command.py",
            "src/asteria_runtime/commands/readiness_run_command.py",
            "src/asteria_runtime/commands/evidence_bundle_command.py",
            "src/asteria_runtime/schemas/readiness_run.schema.json",
        ]
        missing = [item for item in required if not (self.root / item).exists()]
        return PackageCheck(
            "readiness_command_modules",
            not missing,
            (
                "real-model smoke/gate/acceptance package modules present"
                " and gate/readiness/readiness-run command modules present"
                if not missing
                else "missing: " + ", ".join(missing)
            ),
        )

    def _hook_plugin_control_surface_check(self) -> PackageCheck:
        required = [
            "schemas/runtime_hook_event.schema.json",
            "schemas/plugin_manifest.schema.json",
            "src/asteria_runtime/schemas/runtime_hook_event.schema.json",
            "src/asteria_runtime/schemas/plugin_manifest.schema.json",
            "src/asteria_runtime/core/runtime_hooks.py",
            "src/asteria_runtime/core/plugin_manifest.py",
            "src/asteria_runtime/core/plugin_diagnostics.py",
            "src/asteria_runtime/commands/plugins_command.py",
            "templates/policies.default.json",
            "src/asteria_runtime/templates/policies.default.json",
            "docs/zh/工程化体系.md",
            "docs/zh/工程治理体系.md",
        ]
        missing = [item for item in required if not (self.root / item).exists()]
        return PackageCheck(
            "hook_plugin_control_surface",
            not missing,
            (
                "hook/plugin schemas, control command, defaults, and docs present"
                if not missing
                else "missing: " + ", ".join(missing)
            ),
        )

    def _route_template_check(self) -> PackageCheck:
        path = self.root / "templates" / "model.routes.readiness.example.ps1"
        return PackageCheck(
            "readiness_route_template",
            path.exists(),
            str(path.relative_to(self.root)) if path.exists() else "missing readiness route template",
        )

    def _runbook_docs_check(self) -> PackageCheck:
        required = [
            "docs/zh/开发指南.md",
            "docs/zh/运行命令.md",
            "docs/zh/真实模型验收.md",
            "docs/zh/发布准备验证试运行手册.md",
        ]
        missing = [item for item in required if not (self.root / item).exists()]
        return PackageCheck(
            "readiness_docs",
            not missing,
            "readiness rollout docs present" if not missing else "missing: " + ", ".join(missing),
        )

    def _readiness_runbook_check(self) -> PackageCheck:
        path = self.root / "docs" / "zh" / "发布准备验证试运行手册.md"
        return PackageCheck(
            "readiness_runbook",
            path.exists(),
            str(path.relative_to(self.root)) if path.exists() else "missing readiness runbook",
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
