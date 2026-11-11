from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest

import pytest


@pytest.fixture
def checks(monkeypatch):
    module = ModuleType("tinydb")
    module.TinyDB = object
    module.ReadOnlyError = type("ReadOnlyError", (RuntimeError,), {})
    storage = ModuleType("tinydb.storages")
    storage.MemoryStorage = object
    monkeypatch.setitem(sys.modules, "tinydb", module)
    monkeypatch.setitem(sys.modules, "tinydb.storages", storage)
    return runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "benchmarks/dogfood/tinydb_apply_batch_oracle_s123.py.txt"
        )
    )


@pytest.mark.parametrize("fault", [None, "missing", "extra", "wrong", "bool"])
def test_batch_grader_requires_exact_integer_counts(checks, fault):
    actual = {"inserted": 1, "updated": 2, "removed": 3}
    if fault == "missing":
        actual.pop("removed")
    if fault == "extra":
        actual["changed"] = True
    if fault == "wrong":
        actual["removed"] = 4
    if fault == "bool":
        actual["inserted"] = True
    if fault is None:
        checks["assert_counts"](unittest.TestCase(), actual, (1, 2, 3))
    else:
        with pytest.raises(AssertionError):
            checks["assert_counts"](unittest.TestCase(), actual, (1, 2, 3))


@pytest.mark.parametrize("delta", [(1, 1), (2, 1), (1, 2), (0, 1)])
def test_batch_grader_uses_evaluator_owned_io_observations(checks, delta):
    from types import SimpleNamespace

    storage = SimpleNamespace(reads=delta[0], writes=delta[1])
    if delta == (1, 1):
        checks["assert_io"](unittest.TestCase(), storage, (0, 0), 1, 1)
    else:
        with pytest.raises(AssertionError):
            checks["assert_io"](unittest.TestCase(), storage, (0, 0), 1, 1)
