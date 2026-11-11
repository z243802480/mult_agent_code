"""The independent grader checks public outcomes, never a target's storage layout."""

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest

import pytest


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.setitem(sys.modules, "cachetools", ModuleType("cachetools"))
    return runpy.run_path(str(Path(__file__).resolve().parents[2] /
                             "benchmarks/dogfood/cachetools_peekmany_oracle.py.txt"))


@pytest.mark.parametrize("bad", [None, "order", "deduplicated", "copy", "view"])
def test_batch_grader_accepts_identity_list_and_rejects_wrong_results(checks, bad):
    a, b = [], {}
    cases = {None: [b, a, b], "order": [a, b, b], "deduplicated": [b, a],
             "copy": [b, [], b], "view": iter([b, a, b])}
    if bad is None:
        checks["assert_values"](unittest.TestCase(), cases[bad], [b, a, b])
    else:
        with pytest.raises(AssertionError):
            checks["assert_values"](unittest.TestCase(), cases[bad], [b, a, b])


@pytest.mark.parametrize("fault", [None, "purge", "timer"])
def test_expiry_grader_uses_public_expire_and_owned_values(checks, fault):
    value, remaining = object(), {}
    remaining['a'] = value
    clock = SimpleNamespace(now=10, calls=0)

    def peekmany(keys, *default):
        clock.calls += 2 if fault == "timer" else 1
        if fault == "purge":
            remaining.clear()
        if not default:
            raise KeyError(next(iter(keys)))
        return [default[0] for _ in keys]

    cache = SimpleNamespace(peekmany=peekmany, expire=lambda now: list(remaining.items()))
    if fault is None:
        checks["assert_expired_batch"](unittest.TestCase(), cache, clock, 'a', value)
    else:
        with pytest.raises(AssertionError):
            checks["assert_expired_batch"](unittest.TestCase(), cache, clock, 'a', value)
