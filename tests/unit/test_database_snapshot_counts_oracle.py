from copy import deepcopy
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest

import pytest

@pytest.fixture
def checks(monkeypatch):
    modules = {name: ModuleType(name) for name in ('tinydb', 'tinydb.table', 'tinydb.storages')}
    modules['tinydb'].TinyDB = object
    modules['tinydb.table'].Document = type('Document', (dict,), {})
    modules['tinydb.table'].Table = object
    modules['tinydb.storages'].MemoryStorage = object
    modules['tinydb.storages'].JSONStorage = object
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return runpy.run_path(str(Path(__file__).resolve().parents[2] /
                             'benchmarks/dogfood/tinydb_snapshot_counts_oracle_s120.py.txt'))


@pytest.mark.parametrize('fault', [None, 'missing', 'wrong_count', 'bool', 'float'])
def test_counts_grader_requires_complete_integer_counts(checks, fault):
    choices = {None: {'alpha': 1}, 'missing': {}, 'wrong_count': {'alpha': 2},
               'bool': {'alpha': True}, 'float': {'alpha': 1.0}}
    if fault is None:
        checks['assert_counts'](unittest.TestCase(), choices[fault], {'alpha': 1})
    else:
        with pytest.raises(AssertionError):
            checks['assert_counts'](unittest.TestCase(), choices[fault], {'alpha': 1})


@pytest.mark.parametrize('fault', [None, 'extra_read', 'write'])
def test_counts_grader_uses_its_own_storage_instrument(checks, fault):
    case = checks['Counts']('test_all_counts_and_handle_modes')

    def seeded(read_only=False):
        storage = SimpleNamespace(reads=0, writes=0, memory=deepcopy(checks['DATA']))

        class Database:
            def snapshot_counts(self):
                storage.reads += 2 if fault == 'extra_read' else 1
                storage.writes += int(fault == 'write')
                return dict(checks['EXPECTED'])

        return Database(), storage

    case.seeded = seeded
    db, storage = seeded()
    if fault is None:
        case.checked(db, storage)
    else:
        with pytest.raises(AssertionError):
            case.checked(db, storage)
