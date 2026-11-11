from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from asteria_runtime.tools import command_tools
from asteria_runtime.tools.command_tools import RunCommandTool, RunTestsTool


def context(root):
    return SimpleNamespace(root=root, policy={"permissions": {"allow_shell": True}})


def python_command(source):
    return f'"{sys.executable}" -c "{source}"'


def test_check_reports_created_modified_deleted_files_without_cleaning_them(tmp_path):
    (tmp_path / "existing.txt").write_text("before")
    (tmp_path / "obsolete.txt").write_text("old")
    command = python_command(
        "from pathlib import Path; Path('generated.json').write_text('{}'); "
        "Path('existing.txt').write_text('changed content'); Path('obsolete.txt').unlink()"
    )
    ctx = context(tmp_path)
    ctx.policy["permissions"]["allow_destructive_shell"] = True
    result = RunTestsTool().run(ctx, command)
    assert result.ok
    assert result.data["workspace_changes"] == {
        "created": ["generated.json"], "modified": ["existing.txt"], "deleted": ["obsolete.txt"],
    }
    assert result.data["changed_files"] == ["existing.txt", "generated.json", "obsolete.txt"]
    assert "generated.json" in result.summary
    assert "passed" not in result.summary.lower()
    assert (tmp_path / "generated.json").read_text() == "{}"
    assert (tmp_path / "existing.txt").read_text() == "changed content"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipeline exit-status contract")
def test_pipeline_zero_does_not_claim_the_failed_test_passed(tmp_path):
    result = RunTestsTool().run(context(tmp_path), "false | cat")
    assert result.ok and result.data["returncode"] == 0
    assert "Shell command exited 0" in result.summary
    assert "passed" not in result.summary.lower()


def test_scan_unavailable_is_unknown_not_a_clean_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(command_tools, "snapshot_workspace", lambda root: None)
    result = RunCommandTool().run(context(tmp_path), python_command("print('done')"))
    assert result.ok
    assert result.data["workspace_changes"] is None
    assert result.data["workspace_scan"] == "unavailable"
    assert "effects unknown" in result.summary


def test_timeout_keeps_observed_file_side_effects(tmp_path, monkeypatch):
    def interrupted(command, **kwargs):
        (Path(kwargs["cwd"]) / "partial.txt").write_text("partial output")
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(command_tools, "run_fenced", interrupted)
    result = RunCommandTool().run(context(tmp_path), python_command("print('check')"))
    assert not result.ok and result.error == "timeout"
    assert result.data["workspace_changes"]["created"] == ["partial.txt"]
    assert "partial.txt" in result.summary
    assert (tmp_path / "partial.txt").exists()
