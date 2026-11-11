from pathlib import Path
import runpy

import pytest


@pytest.mark.parametrize('text, expected', [
    ('>>> 1 + 1\n2\n', (1, 0)),
    ('>>> 1 + 1\n1\n', (1, 1)),
    ('Only prose; no runnable example.', (0, 1)),
])
def test_example_checker_requires_execution_and_matching_outputs(text, expected):
    checks = runpy.run_path(str(Path(__file__).resolve().parents[2] /
        'benchmarks/dogfood/tinydb_batch_examples_s123.py.txt'))
    assert checks['verify_section'](text, 'example.rst') == expected


@pytest.mark.parametrize('usage, api, failures', [
    ('>>> 1 + 1\n2\n', 'API prose only.\n', 0),
    ('>>> 1 + 1\n1\n', 'API prose only.\n', 1),
    ('No executable usage.\n', 'API prose only.\n', 1),
    ('>>> 1 + 1\n2\n', '>>> 2 + 2\n3\n', 1),
])
def test_doc_audit_oracle_checks_claims_without_requiring_new_api_examples(
    tmp_path, usage, api, failures,
):
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'usage.rst').write_text('Batch Operations\n' + usage + '\nQueries\n', encoding='utf8')
    (docs / 'api.rst').write_text('Batch API\n' + api + '``tinydb.database``', encoding='utf8')
    checks = runpy.run_path(str(Path(__file__).resolve().parents[2] /
        'benchmarks/dogfood/tinydb_doc_audit_oracle_s124.py.txt'))
    assert checks['verify'](tmp_path) == failures


@pytest.mark.parametrize('text, failures', [
    ('>>> 1 + 1\n2\n', 0), ('>>> 1 + 1\n1\n', 1), ('Only prose.', 1),
])
def test_remove_oracle_requires_actual_matching_doctest(text, failures):
    checks = runpy.run_path(str(Path(__file__).resolve().parents[2] /
        'benchmarks/dogfood/tinydb_remove_doc_oracle_s126.py.txt'))
    assert checks['check'](text, 'remove-example') == failures
