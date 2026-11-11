"""Check the external grader independently of any TinyDB implementation."""

from pathlib import Path
from copy import deepcopy
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest

import pytest


@pytest.fixture
def checks(monkeypatch):
    class Document(dict):
        def __init__(self, value, doc_id):
            super().__init__(value)
            self.doc_id = doc_id

    modules = {name: ModuleType(name) for name in ('tinydb', 'tinydb.table', 'tinydb.storages')}
    modules['tinydb'].TinyDB = object
    modules['tinydb.table'].Document = Document
    modules['tinydb.table'].Table = object
    modules['tinydb.storages'].MemoryStorage = object
    modules['tinydb.storages'].JSONStorage = object
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return runpy.run_path(str(Path(__file__).resolve().parents[2] /
                             'benchmarks/dogfood/tinydb_snapshot_oracle.py.txt'))


@pytest.mark.parametrize('fault', [None, 'duplicate', 'wrong_id', 'wrong_data', 'plain_dict', 'missing_table'])
def test_snapshot_grader_accepts_public_documents_and_rejects_bad_results(checks, fault):
    document = checks['Document']({'value': [1]}, 7)
    cases = {None: {'alpha': [document]}, 'duplicate': {'alpha': [document, document]},
             'wrong_id': {'alpha': [checks['Document']({'value': [1]}, 8)]},
             'wrong_data': {'alpha': [checks['Document']({'value': [2]}, 7)]},
             'plain_dict': {'alpha': [{'value': [1]}]}, 'missing_table': {}}
    expected = {'alpha': {'7': {'value': [1]}}}
    if fault is None:
        checks['assert_snapshot'](unittest.TestCase(), cases[fault], expected)
    else:
        with pytest.raises(AssertionError):
            checks['assert_snapshot'](unittest.TestCase(), cases[fault], expected)


def test_snapshot_grader_accepts_subclasses_and_unspecified_document_order(checks):
    class CustomDocument(checks['Document']):
        pass

    checks['assert_snapshot'](unittest.TestCase(), {'alpha': [CustomDocument({}, 9), CustomDocument({}, 1)]},
                              {'alpha': {'1': {}, '9': {}}})


@pytest.mark.parametrize('fault', [None, 'alias', 'extra_read', 'write'])
def test_full_mutation_check_detects_shared_values_and_storage_side_effects(checks, fault):
    case = checks['Snapshot']('test_nested_values_doc_ids_and_membership_are_detached')

    def seeded(read_only=False):
        storage = SimpleNamespace(memory=deepcopy(checks['DATA']), reads=0, writes=0)

        class Database:
            def snapshot(self):
                storage.reads += 2 if fault == 'extra_read' else 1
                storage.writes += int(fault == 'write')
                data = storage.memory if fault == 'alias' else deepcopy(storage.memory)
                return {name: [checks['Document'](doc, int(key)) for key, doc in documents.items()]
                        for name, documents in data.items()}

        return Database(), storage

    case.seeded = seeded
    if fault is None:
        case.test_nested_values_doc_ids_and_membership_are_detached()
    else:
        with pytest.raises(AssertionError):
            case.test_nested_values_doc_ids_and_membership_are_detached()
