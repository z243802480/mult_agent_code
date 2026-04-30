from __future__ import annotations

import base64
import re


def normalize_verification_command(command: str, task: dict) -> str:
    stripped = command.strip()
    cleanup_command = _normalize_safe_test_cleanup(stripped)
    if cleanup_command is not None:
        return cleanup_command
    fixture_command = _normalize_shell_fixture_setup(stripped, task)
    if fixture_command is not None:
        return fixture_command
    # Real models often append this shell idiom to keep usage checks non-fatal.
    # The runtime has expected_returncodes for that, so remove only this safe suffix.
    stripped = re.sub(r"\s+2>&1\s+\|\|\s+true\s*$", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s+\|\|\s+true\s*$", "", stripped, flags=re.IGNORECASE)
    return stripped


def _normalize_safe_test_cleanup(command: str) -> str | None:
    match = re.fullmatch(r"rm\s+-rf\s+([A-Za-z0-9_.\-/\\]+)", command, flags=re.IGNORECASE)
    if not match:
        return None
    path = match.group(1).strip().strip("'\"")
    if not _is_safe_test_fixture_path(path):
        return None
    encoded_path = repr(_b64(path))
    code = (
        "from pathlib import Path; import base64, shutil; "
        f"p=Path(base64.b64decode({encoded_path}).decode()); "
        "shutil.rmtree(p) if p.exists() else None"
    )
    return f'python -c "{code}"'


def _normalize_shell_fixture_setup(command: str, task: dict) -> str | None:
    if "&&" not in command or ">" not in command:
        return None
    dirs: list[str] = []
    files: list[tuple[str, str]] = []
    final_command: str | None = None
    segments = [segment.strip() for segment in command.split("&&")]
    for index, part in enumerate(segments):
        if index == 0 and re.fullmatch(r"cd\s+(/\w+|[A-Za-z]:[\\/][\w.\-/\\]+)", part, flags=re.IGNORECASE):
            continue
        mkdir_match = re.fullmatch(r"mkdir\s+-p\s+(.+)", part, flags=re.IGNORECASE)
        if mkdir_match:
            dirs.append(mkdir_match.group(1).strip().strip("'\""))
            continue
        echo_match = re.fullmatch(
            r"echo\s+(?:-e\s+)?(?:\"([^\"]*)\"|'([^']*)'|([^>]+?))\s*>\s*(.+)",
            part,
            flags=re.IGNORECASE,
        )
        if echo_match:
            double_quoted, single_quoted, unquoted, raw_path = echo_match.groups()
            files.append(
                (
                    raw_path.strip().strip("'\""),
                    (
                        double_quoted
                        if double_quoted is not None
                        else single_quoted
                        if single_quoted is not None
                        else unquoted
                    ).strip(),
                )
            )
            continue
        if index == len(segments) - 1 and re.fullmatch(
            r"echo\s+(?:\"[^\"]*\"|'[^']*'|.+)",
            part,
            flags=re.IGNORECASE,
        ):
            continue
        if index == len(segments) - 1:
            final_command = _rewrite_simple_python_command(part, task)
            if final_command is None:
                return None
            continue
        return None
    if not files:
        return None
    encoded_dirs = repr([_b64(item) for item in dirs])
    encoded_files = repr([(_b64(path), _b64(content)) for path, content in files])
    run_suffix = ""
    if final_command is not None:
        encoded_command = repr(_b64(final_command))
        run_suffix = (
            f"; cmd=base64.b64decode({encoded_command}).decode(); "
            "args=shlex.split(cmd); "
            "args[0]=sys.executable if args and args[0].lower() in ('python','python3','py') else args[0]; "
            "sys.exit(subprocess.run(args).returncode)"
        )
    code = (
        "from pathlib import Path; import base64, shlex, subprocess, sys; "
        f"dirs={encoded_dirs}; files={encoded_files}; "
        "[Path(base64.b64decode(d).decode()).mkdir(parents=True, exist_ok=True) for d in dirs]; "
        "[(lambda p,t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t, encoding='utf-8')))"
        "(Path(base64.b64decode(p).decode()), base64.b64decode(t).decode()) for p,t in files]"
        f"{run_suffix}"
    )
    return f'python -c "{code}"'


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _rewrite_simple_python_command(command: str, task: dict) -> str | None:
    if any(operator in command for operator in ("&&", "||", ";", "|", ">", "<")):
        return None
    match = re.match(r"^(python3?|py)\s+([\w./\\:\-]+\.py)(.*)$", command, flags=re.IGNORECASE)
    if not match:
        return None
    python_name, script_path, rest = match.groups()
    script_name = script_path.replace("\\", "/").rsplit("/", 1)[-1]
    expected_artifacts = {
        str(artifact).replace("\\", "/").rsplit("/", 1)[-1]
        for artifact in task.get("expected_artifacts", [])
        if isinstance(artifact, str)
    }
    if script_name in expected_artifacts:
        script_path = script_name
    if not re.fullmatch(r"(?:\s+[\w./\\:\-]+)*\s*", rest):
        return None
    return f"{python_name} {script_path}{rest}"


def _is_safe_test_fixture_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return False
    if path.startswith(("/", "\\")) or ":" in path:
        return False
    return parts[0].lower().startswith("test")
