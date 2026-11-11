"""Verify the evaluator's observations, without importing a target or its solution."""

from copy import deepcopy
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def oracle(monkeypatch):
    # Minimal seeding doubles: these have no read-only implementation or query engine.
    class Storage:
        def __init__(self, *args, **kwargs):
            self.data = None

        def read(self):
            return self.data

        def write(self, data):
            self.data = data

        def close(self):
            pass

    class OpaqueStorage:
        def __init__(self, raw):
            self.read, self.close = raw.read, raw.close

    class Database:
        def __init__(self, *args, storage, read_only=False, **kwargs):
            raw = storage(*args, **kwargs)
            self.storage = OpaqueStorage(raw) if read_only else raw

        def insert_multiple(self, documents):
            self.storage.write({"_default": dict(enumerate(deepcopy(documents), 1))})

        def table(self, name):
            return SimpleNamespace(insert=lambda document: None)

        def close(self):
            self.storage.close()

    module, storages = ModuleType("tinydb"), ModuleType("tinydb.storages")
    module.TinyDB, module.Query, module.ReadOnlyError = Database, object, PermissionError
    storages.MemoryStorage = storages.JSONStorage = Storage
    monkeypatch.setitem(sys.modules, "tinydb", module)
    monkeypatch.setitem(sys.modules, "tinydb.storages", storages)
    path = Path(__file__).resolve().parents[2] / "benchmarks/dogfood/tinydb_readonly_oracle_s113.py.txt"
    namespace = runpy.run_path(str(path))
    case = namespace["ReadOnlyHandles"]()
    case.setUp()
    yield case
    case.tearDown()


@pytest.mark.parametrize("kind", ["memory", "json"])
def test_owned_observer_accepts_opaque_storage_wrapper(oracle, kind):
    db, path = oracle.seeded(kind)
    assert not hasattr(db.storage, "writes")

    def refused():
        raise PermissionError("refused before touching data")

    oracle.blocked(db, path, refused, [])


def test_write_then_raise_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    raw = oracle.observed_storages[id(db)]

    def bad_refusal():
        raw.write(deepcopy(raw.read()))
        raise PermissionError("too late")

    with pytest.raises(AssertionError):
        oracle.blocked(db, path, bad_refusal)


def test_callback_then_raise_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    seen = []

    def bad_refusal():
        seen.append("callback ran")
        raise PermissionError("too late")

    with pytest.raises(AssertionError, match="write refusal must precede"):
        oracle.blocked(db, path, bad_refusal, seen)


def test_nested_mutation_without_write_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    raw = oracle.observed_storages[id(db)]

    def bad_refusal():
        raw.read()["_default"][1]["nested"]["items"].append(99)
        raise PermissionError("too late")

    with pytest.raises(AssertionError):
        oracle.blocked(db, path, bad_refusal)


def test_no_exception_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    with pytest.raises(AssertionError, match="not raised"):
        oracle.blocked(db, path, lambda: None)


def test_returned_document_alias_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    raw = oracle.observed_storages[id(db)]
    oracle.seeded = lambda kind: (db, path)
    # The read grader must reject a document that aliases evaluator-owned storage.
    with pytest.raises(AssertionError):
        oracle.detached_reads("memory", lambda handle: raw.read()["_default"][1])


def test_disk_write_then_raise_is_still_rejected(oracle):
    db, path = oracle.seeded("memory")
    path.write_bytes(b"original bytes")

    def bad_refusal():
        path.write_bytes(b"changed bytes")
        raise PermissionError("too late")

    with pytest.raises(AssertionError):
        oracle.blocked(db, path, bad_refusal)
