from collections.abc import Mapping
from pathlib import Path
import runpy
import sys
from types import MappingProxyType, ModuleType
import unittest

import pytest


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.setitem(sys.modules, 'cachetools', ModuleType('cachetools'))
    return runpy.run_path(str(Path(__file__).resolve().parents[2] /
                             'benchmarks/dogfood/cachetools_snapshot_oracle_s118.py.txt'))


@pytest.mark.parametrize('representation', ['proxy', 'custom'])
def test_grader_accepts_public_immutable_mapping_representations(checks, representation):
    value = []

    class Frozen(Mapping):
        def __iter__(self):
            return iter(['a'])

        def __len__(self):
            return 1

        def __getitem__(self, key):
            if key == 'a':
                return value
            raise KeyError(key)

    result = MappingProxyType({'a': value}) if representation == 'proxy' else Frozen()
    checks['assert_members'](unittest.TestCase(), result, {'a': value})
    checks['assert_immutable'](unittest.TestCase(), result)


@pytest.mark.parametrize('fault', ['mutable', 'missing', 'copied', 'wrong_container'])
def test_grader_rejects_bad_membership_identity_and_mutability(checks, fault):
    value = []
    cases = {'mutable': {'a': value}, 'missing': MappingProxyType({}),
             'copied': MappingProxyType({'a': []}), 'wrong_container': [('a', value)]}
    with pytest.raises(AssertionError):
        checks['assert_members'](unittest.TestCase(), cases[fault], {'a': value})
        checks['assert_immutable'](unittest.TestCase(), cases[fault])
