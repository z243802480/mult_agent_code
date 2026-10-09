import json
import os
from pathlib import Path

import pytest

from asteria_runtime.storage.durability import fsync_existing_file
from asteria_runtime.storage.file_backup import FileBackupStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.core.runtime_context import RuntimeContext

pytestmark = pytest.mark.workflow

# Reaudit debt #5②: every storage write is now flush+fsync'd at the chokepoints. close()
# alone only reaches the OS page cache — process kills survive that, power loss does not.
# These tests pin that the fsync actually happens on each path (and that failures are
# loud, not swallowed).


def test_jsonl_append_fsyncs_each_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    path = tmp_path / "events.jsonl"

    JsonlStore().append(path, {"n": 1})
    JsonlStore().append(path, {"n": 2})

    assert len(calls) == 2
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["n"] for row in rows] == [1, 2]


def test_json_store_write_fsyncs_before_replace_and_leaves_no_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    path = tmp_path / "run.json"

    JsonStore().write(path, {"status": "completed"})

    assert calls, "state flip must be fsynced before the atomic rename"
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "completed"}
    assert not (tmp_path / "run.json.tmp").exists()


def test_jsonl_rewrite_all_fsyncs_the_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    path = tmp_path / "rows.jsonl"
    path.write_text('{"n": 1}\n', encoding="utf-8")

    JsonlStore().rewrite_all(path, [{"n": 9}])

    assert calls, "rewrite is the file's state of record — must be fsynced pre-rename"
    assert [json.loads(line)["n"] for line in path.read_text(encoding="utf-8").splitlines()] == [9]


def test_fsync_errors_propagate_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_fsync(fd: int) -> None:
        raise OSError("device gone")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        JsonlStore().append(tmp_path / "x.jsonl", {"n": 1})
    with pytest.raises(OSError):
        JsonStore().write(tmp_path / "x.json", {"n": 1})


def test_backup_paths_fsyncs_the_copied_user_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tool.py").write_text("print('hi')\n", encoding="utf-8")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=SchemaValidator(Path.cwd() / "schemas"),
    )

    manifest = FileBackupStore(context).backup_paths(
        [tmp_path / "src" / "tool.py"], reason="test"
    )

    assert calls, "a torn backup copy would defeat the file-restore safety net"
    backup_rel = manifest["files"][0]["backup_path"]
    backup_file = context.asteria_dir / "backups" / "run-1" / manifest["backup_id"] / backup_rel
    assert backup_file.read_text(encoding="utf-8") == "print('hi')\n"
    fsync_existing_file(backup_file)  # reopen-with-write-access path stays usable
