from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest

import pytest


@pytest.mark.parametrize('fault', [None, 'shape', 'missing', 'duplicate', 'order', 'identity', 'alias'])
def test_partition_grader_checks_both_independent_ordered_lists(monkeypatch, fault):
    monkeypatch.setitem(sys.modules, 'cachetools', ModuleType('cachetools'))
    checks = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                               'benchmarks/dogfood/cachetools_partition_oracle_s122.py.txt'))
    a, b, c = object(), object(), object()
    expected = ([('a', a), ('b', b)], [('c', c)])
    shared = []
    actual = {
        None: expected,
        'shape': list(expected),
        'missing': (expected[0], []),
        'duplicate': (expected[0], [('a', a)]),
        'order': (expected[0][::-1], expected[1]),
        'identity': (expected[0], [('c', object())]),
        'alias': (shared, shared),
    }[fault]
    if fault is None:
        checks['assert_partition'](unittest.TestCase(), actual, expected)
    else:
        with pytest.raises(AssertionError):
            checks['assert_partition'](unittest.TestCase(), actual, expected)
