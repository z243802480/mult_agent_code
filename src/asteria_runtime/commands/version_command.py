from __future__ import annotations

import sys
from dataclasses import dataclass

from asteria_runtime import __version__
from asteria_runtime.commands.control_surface_contract import control_surface_contract


@dataclass(frozen=True)
class VersionResult:
    package: str = "asteria-runtime"
    version: str = __version__
    python_version: str = sys.version.split()[0]
    executable: str = sys.executable

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="version",
                audience="maintainer_preflight",
                stable_fields=[
                    "schema_version",
                    "package",
                    "version",
                    "python_version",
                    "executable",
                ],
            ),
            "package": self.package,
            "version": self.version,
            "python_version": self.python_version,
            "executable": self.executable,
        }

    def to_text(self) -> str:
        return "\n".join(
            [
                f"{self.package} {self.version}",
                f"Python: {self.python_version}",
                f"Executable: {self.executable}",
            ]
        )


class VersionCommand:
    def run(self) -> VersionResult:
        return VersionResult()
