from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StudioLaunchResult:
    root: Path
    runtime_root: Path
    studio_dir: Path
    api_url: str
    ui_url: str
    api_port: int
    ui_port: int
    backend_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "runtime_root": str(self.runtime_root),
            "studio_dir": str(self.studio_dir),
            "api_url": self.api_url,
            "ui_url": self.ui_url,
            "api_port": self.api_port,
            "ui_port": self.ui_port,
            "backend_only": self.backend_only,
        }

    def to_text(self) -> str:
        lines = [
            "Asteria Studio is running.",
            f"- workspace: {self.root}",
            f"- API: {self.api_url}",
        ]
        if not self.backend_only:
            lines.append(f"- UI: {self.ui_url}")
        lines.append("Press Ctrl+C to stop.")
        return "\n".join(lines)


class StudioCommand:
    def __init__(
        self,
        root: Path,
        *,
        runtime_root: Path | None = None,
        studio_dir: Path | None = None,
        api_port: int = 8787,
        ui_port: int = 5174,
        python: str | None = None,
        backend_only: bool = False,
        skip_install: bool = False,
        open_browser: bool = True,
    ) -> None:
        self.root = root.resolve()
        self.runtime_root = (runtime_root or self.root).resolve()
        self.studio_dir = (studio_dir or resolve_studio_dir()).resolve()
        self.api_port = api_port
        self.ui_port = ui_port
        self.python = python or sys.executable
        self.backend_only = backend_only
        self.skip_install = skip_install
        self.open_browser = open_browser

    def preview(self) -> StudioLaunchResult:
        self._validate()
        return StudioLaunchResult(
            root=self.root,
            runtime_root=self.runtime_root,
            studio_dir=self.studio_dir,
            api_url=f"http://127.0.0.1:{self.api_port}",
            ui_url=f"http://127.0.0.1:{self.ui_port}",
            api_port=self.api_port,
            ui_port=self.ui_port,
            backend_only=self.backend_only,
        )

    def run(self) -> StudioLaunchResult:
        self._validate()
        if not self.skip_install:
            self._ensure_node_modules()
        result = self.preview()
        processes: list[subprocess.Popen[bytes]] = []
        try:
            processes.append(self._start_api_server())
            if not self.backend_only:
                processes.append(self._start_ui_server())
            if self.open_browser and not self.backend_only:
                time.sleep(1.0)
                webbrowser.open(ui_url)
            self._wait_until_stopped(processes)
        finally:
            self._terminate_processes(processes)
        return result

    def _validate(self) -> None:
        if not self.studio_dir.is_dir():
            raise FileNotFoundError(
                f"Studio directory not found: {self.studio_dir}. "
                "Set ASTERIA_STUDIO_DIR or run from a repo checkout."
            )
        server_script = self.studio_dir / "server.mjs"
        if not server_script.is_file():
            raise FileNotFoundError(f"Missing Studio server entrypoint: {server_script}")

    def _ensure_node_modules(self) -> None:
        node_modules = self.studio_dir / "node_modules"
        if node_modules.is_dir():
            return
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to install Studio dependencies.")
        subprocess.run(
            [npm, "install"],
            cwd=self.studio_dir,
            check=True,
        )

    def _start_api_server(self) -> subprocess.Popen[bytes]:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node is required to launch Asteria Studio.")
        env = os.environ.copy()
        env.setdefault("ASTERIA_STUDIO_PORT", str(self.api_port))
        return subprocess.Popen(
            [
                node,
                "server.mjs",
                "--workspace",
                str(self.root),
                "--runtime-root",
                str(self.runtime_root),
                "--port",
                str(self.api_port),
                "--python",
                self.python,
            ],
            cwd=self.studio_dir,
            env=env,
        )

    def _start_ui_server(self) -> subprocess.Popen[bytes]:
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to launch the Studio UI.")
        env = os.environ.copy()
        return subprocess.Popen(
            [
                npm,
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.ui_port),
            ],
            cwd=self.studio_dir,
            env=env,
        )

    @staticmethod
    def _wait_until_stopped(processes: list[subprocess.Popen[bytes]]) -> None:
        def _handle_stop(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        previous_int = signal.signal(signal.SIGINT, _handle_stop)
        previous_term = signal.signal(signal.SIGTERM, _handle_stop)
        try:
            while True:
                for process in processes:
                    code = process.poll()
                    if code is not None:
                        raise RuntimeError(
                            f"Studio child process exited unexpectedly (code={code})."
                        )
                time.sleep(1.0)
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)

    @staticmethod
    def _terminate_processes(processes: list[subprocess.Popen[bytes]]) -> None:
        for process in processes:
            if process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def resolve_studio_dir() -> Path:
    env_dir = os.environ.get("ASTERIA_STUDIO_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "studio"
