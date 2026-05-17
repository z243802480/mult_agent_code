from __future__ import annotations

import sys
from dataclasses import dataclass

from asteria_runtime import __version__


@dataclass(frozen=True)
class VersionResult:
    package: str = "asteria-runtime"
    version: str = __version__
    python_version: str = sys.version.split()[0]
    executable: str = sys.executable

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
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
