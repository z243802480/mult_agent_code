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
