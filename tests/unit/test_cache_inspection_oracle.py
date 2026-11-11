"""Grader checks accept opaque public-API representations and reject real bad outcomes."""

import runpy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

import pytest


@pytest.fixture
def checks(monkeypatch):
    # Loading the helper definitions needs no target source, dependency or solution.
    monkeypatch.setitem(sys.modules, "cachetools", ModuleType("cachetools"))
    return runpy.run_path(str(Path(__file__).resolve().parents[2] /
                             "benchmarks/dogfood/cachetools_peek_oracle.py.txt"))


@pytest.mark.parametrize("pairs_as_lists", [False, True])
def test_snapshot_grader_allows_equivalent_pairs_and_preserves_owned_value_identity(checks, pairs_as_lists):
    value = []
    pairs = [["a", value]] if pairs_as_lists else [("a", value)]
    checks["assert_snapshot"](unittest.TestCase(), pairs, {"a": value})


@pytest.mark.parametrize("bad", ["duplicate", "missing", "copied_value", "live_view"])
def test_snapshot_grader_rejects_wrong_membership_identity_or_container(checks, bad):
    value = []
    choices = {
        "duplicate": [("a", value), ("a", value)], "missing": [],
        "copied_value": [("a", [])], "live_view": {"a": value}.items(),
    }
    with pytest.raises(AssertionError):
        checks["assert_snapshot"](unittest.TestCase(), choices[bad], {"a": value})


@pytest.mark.parametrize("purge", [False, True])
def test_expiry_grader_observes_public_expire_without_private_storage_assumptions(checks, purge):
    value, remaining = object(), []
    remaining.append(("a", value))

    def peek(key, *default):
        if purge:
            remaining.clear()
        if default:
            return default[0]
        raise KeyError(key)

    # The grader gets only public methods; its expected values are caller-owned.
    opaque = SimpleNamespace(peek=peek, peekitems=lambda: [], expire=lambda now: list(remaining))
    clock = SimpleNamespace(now=5)
    if purge:
        with pytest.raises(AssertionError, match="must not purge"):
            checks["assert_expired_remains"](unittest.TestCase(), opaque, clock, {"a": value})
    else:
        checks["assert_expired_remains"](unittest.TestCase(), opaque, clock, {"a": value})
