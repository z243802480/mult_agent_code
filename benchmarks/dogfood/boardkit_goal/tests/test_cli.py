import csv
import io
import json
import subprocess
import sys

from boardkit.formats import to_csv
from boardkit.store import Store


def cli(db, *args):
    return subprocess.run([sys.executable, "-m", "boardkit", "--db", str(db), *args], capture_output=True, text=True, timeout=10)


def value(db, *args):
    result = cli(db, *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_cli_crud_comments_and_error_exit(tmp_path):
    db = tmp_path / "cli.db"
    item = value(db, "add", " first ", "--tag", "Z", "--tag", "a")
    item_id = str(item["id"])
    assert item["tags"] == ["a", "z"]
    updated = value(db, "set", item_id, "--version", "1", "--status", "doing", "--title", "second")
    assert updated["title"] == "second" and updated["version"] == 2
    commented = value(db, "comment", item_id, "--version", "2", "note")
    assert commented["comments"][0]["text"] == "note"
    assert value(db, "show", item_id) == commented
    assert value(db, "list", "--status", "doing", "--tag", "A", "--query", "SECOND")["total"] == 1
    error = cli(db, "delete", item_id, "--version", "1")
    assert error.returncode == 2 and error.stderr.strip() and "Traceback" not in error.stderr
    assert value(db, "delete", item_id, "--version", "3") == {"deleted": item["id"]}
    error = cli(db, "show", item_id)
    assert error.returncode == 2 and "Traceback" not in error.stderr


def test_cli_snapshot_import_export_and_csv(tmp_path):
    db, other = tmp_path / "one.db", tmp_path / "two.db"
    item = value(db, "add", "comma,title", "--tag", "b")
    snapshot = value(db, "export")
    assert snapshot["schema_version"] == 1 and snapshot["items"][0] == item
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert value(other, "import", str(path)) == {"imported": 1}
    assert value(other, "export") == snapshot
    result = cli(other, "export", "--format", "csv")
    assert result.returncode == 0, result.stderr
    assert list(csv.DictReader(io.StringIO(result.stdout)))[0]["title"] == "comma,title"


def test_cli_bad_import_keeps_state(tmp_path):
    db = tmp_path / "state.db"
    item = value(db, "add", "keep")
    path = tmp_path / "broken.json"
    path.write_text('{"schema_version":1,"items":[', encoding="utf-8")
    error = cli(db, "import", str(path))
    assert error.returncode == 2 and "Traceback" not in error.stderr
    assert value(db, "show", str(item["id"])) == item


def test_csv_exact_columns_and_quoting(tmp_path):
    store = Store(tmp_path / "csv.db")
    item = store.create('A,"B"\nC', ["b", "a"])
    text = to_csv([item])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == ["id", "title", "status", "tags", "version"]
    assert rows[0]["title"] == item["title"]
    assert rows[0]["tags"] == "a;b" and rows[0]["version"] == "1"
    assert to_csv([]).strip() == "id,title,status,tags,version"
