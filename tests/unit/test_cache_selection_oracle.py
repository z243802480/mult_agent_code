from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest

import pytest


@pytest.mark.parametrize('fault', [None, 'missing', 'duplicate', 'order', 'identity', 'not_list'])
def test_selection_grader_checks_public_result_without_private_layout(monkeypatch, fault):
    monkeypatch.setitem(sys.modules, 'cachetools', ModuleType('cachetools'))
    checks = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                               'benchmarks/dogfood/cachetools_select_items_oracle_s121.py.txt'))
    values = [object(), object()]
    expected = [('a', values[0]), ('b', values[1])]
    actual = {
        None: list(expected),
        'missing': expected[:1],
        'duplicate': [expected[0], expected[0]],
        'order': expected[::-1],
        'identity': [('a', object()), expected[1]],
        'not_list': tuple(expected),
    }[fault]
    if fault is None:
        checks['assert_selection'](unittest.TestCase(), actual, expected)
    else:
        with pytest.raises(AssertionError):
            checks['assert_selection'](unittest.TestCase(), actual, expected)
