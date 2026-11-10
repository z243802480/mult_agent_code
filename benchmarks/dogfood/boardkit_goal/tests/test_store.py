import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from boardkit.errors import ConflictError, NotFoundError
from boardkit.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "board.db")


def test_create_normalizes_and_reopens(store):
    item = store.create("  Ship local board  ", [" Beta ", "beta", "ALPHA"])
    assert item["title"] == "Ship local board"
    assert item["tags"] == ["alpha", "beta"]
    assert item["status"] == "open" and item["version"] == 1 and item["id"] > 0
    assert item["comments"] == []
    assert datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    assert Store(store.path).get(item["id"]) == item
    item["tags"].append("changed")
    assert "changed" not in store.get(item["id"])["tags"]


@pytest.mark.parametrize("title,tags", [("", None), ("  ", []), ("x" * 121, []), (None, []), ("ok", "tag"), ("ok", [""]), ("ok", [1]), ("ok", ["a" * 25]), ("ok", list("abcdefghi"))])
def test_create_rejects_invalid_without_mutation(store, title, tags):
    with pytest.raises(ValueError):
        store.create(title, tags)
    assert store.list()["total"] == 0


def test_idempotency_is_normalized_and_conflicts_are_atomic(store):
    first = store.create(" title ", [" B ", "a"], "key-1")
    assert store.create("title", ["a", "b"], "key-1") == first
    with pytest.raises(ConflictError):
        store.create("different", ["a", "b"], "key-1")
    assert store.list()["total"] == 1
    assert store.get(first["id"]) == first


def test_filters_paginate_stably(store):
    one = store.create("Alpha one", ["red"])
    two = store.create("Beta two", ["blue"])
    three = store.create("Alpha three", ["red"])
    store.update(two["id"], 1, status="done")
    page = store.list(status="open", tag=" RED ", query="ALPHA", limit=1, offset=1)
    assert page["total"] == 2
    assert [row["id"] for row in page["items"]] == [three["id"]]
    assert [row["id"] for row in store.list()["items"]] == [one["id"], two["id"], three["id"]]


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1}, {"offset": True}, {"status": "invalid"}])
def test_invalid_filters(store, kwargs):
    with pytest.raises(ValueError):
        store.list(**kwargs)


def test_update_delete_and_version_conflicts(store):
    item = store.create("first", ["a"])
    updated = store.update(item["id"], 1, title=" second ", status="doing", tags=["B"])
    assert (updated["title"], updated["status"], updated["tags"], updated["version"]) == ("second", "doing", ["b"], 2)
    assert updated["created_at"] == item["created_at"]
    with pytest.raises(ConflictError):
        store.update(item["id"], 1, title="bad")
    with pytest.raises(ConflictError):
        store.delete(item["id"], 1)
    assert store.get(item["id"]) == updated
    store.delete(item["id"], 2)
    with pytest.raises(NotFoundError):
        store.get(item["id"])


@pytest.mark.parametrize("kwargs", [{"title": ""}, {"status": "bad"}, {"tags": [""]}, {"expected_version": True}])
def test_bad_update_is_atomic(store, kwargs):
    item = store.create("first")
    args = {"expected_version": 1, **kwargs}
    with pytest.raises(ValueError):
        store.update(item["id"], **args)
    assert store.get(item["id"]) == item


def test_comments_use_same_version_and_persist(store):
    item = store.create("topic")
    updated = store.add_comment(item["id"], "  useful note  ", 1)
    assert updated["version"] == 2
    assert updated["comments"][0]["text"] == "useful note"
    assert updated["comments"][0]["created_at"]
    with pytest.raises(ConflictError):
        store.add_comment(item["id"], "stale", 1)
    assert Store(store.path).get(item["id"]) == updated


@pytest.mark.parametrize("text", ["", "  ", "x" * 1001, None])
def test_bad_comment_is_atomic(store, text):
    item = store.create("topic")
    with pytest.raises(ValueError):
        store.add_comment(item["id"], text, 1)
    assert store.get(item["id"]) == item


def test_missing_items(store):
    for operation in (lambda: store.get(999), lambda: store.update(999, 1, title="x"), lambda: store.delete(999, 1), lambda: store.add_comment(999, "x", 1)):
        with pytest.raises(NotFoundError):
            operation()


def test_concurrent_creates_and_compare_and_swap(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda i: Store(store.path).create(f"task {i}"), range(40)))
    assert len({item["id"] for item in items}) == 40
    assert store.list(limit=100)["total"] == 40
    item = items[0]

    def race(i):
        try:
            Store(store.path).update(item["id"], 1, title=f"winner {i}")
            return True
        except ConflictError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(race, range(8))) == 1
    assert store.get(item["id"])["version"] == 2


def test_snapshot_round_trip_and_next_id(store, tmp_path):
    item = store.create("one", ["b", "a"])
    store.add_comment(item["id"], "note", 1)
    snapshot = store.export_snapshot()
    other = Store(tmp_path / "other.db")
    other.import_snapshot(snapshot)
    assert other.export_snapshot() == snapshot
    assert other.create("next")["id"] > item["id"]


@pytest.mark.parametrize("corruption", ["schema", "duplicate", "title", "version", "comments"])
def test_invalid_snapshot_does_not_replace_previous_state(store, corruption):
    item = store.create("keep")
    snapshot = copy.deepcopy(store.export_snapshot())
    if corruption == "schema":
        snapshot["schema_version"] = 2
    elif corruption == "duplicate":
        snapshot["items"].append(copy.deepcopy(snapshot["items"][0]))
    elif corruption == "title":
        snapshot["items"][0]["title"] = ""
    elif corruption == "version":
        snapshot["items"][0]["version"] = 0
    else:
        snapshot["items"][0]["comments"] = [{"wrong": "shape"}]
    with pytest.raises(ValueError):
        store.import_snapshot(snapshot)
    assert store.get(item["id"]) == item
