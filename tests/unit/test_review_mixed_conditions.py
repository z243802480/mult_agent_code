"""A fair paired-scope evaluation corpus, not a new runtime gate."""
import runpy
from pathlib import Path
import sys
from types import ModuleType
import unittest

import pytest

F = runpy.run_path(str(Path(__file__).resolve().parents[2] / "benchmarks/review_cases/mixed_window_guide.py"))


@pytest.mark.parametrize("case", list(F["CASES"]))
def test_independent_oracle_labels_each_defect_without_restricting_equivalent_code(case):
    _, api, guide, expected = F["CASES"][case]
    namespace = {}
    exec(api, namespace)
    result = F["verify"](namespace["parse_window"], guide)
    assert result["count"] == 25 and result["ok"] is expected
    assert result["api"]["ok"] is (not case.startswith("api-"))
    assert result["guide"]["ok"] is (not case.startswith("guide-"))


@pytest.mark.parametrize("case", list(F["CASES"]))
def test_existing_project_checks_are_insufficient_for_both_defect_families(monkeypatch, case):
    module = ModuleType("window")
    exec(F["CASES"][case][1], module.__dict__)
    monkeypatch.setitem(sys.modules, "window", module)
    namespace = {}
    exec(F["PROJECT_CHECKS"], namespace)
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(namespace["WindowTests"]).run(result)
    assert result.testsRun == 2 and result.wasSuccessful()


@pytest.mark.parametrize("pair", [("api-alone", "api-mixed"), ("guide-alone", "guide-mixed")])
def test_paired_controls_have_identical_current_artifacts_and_only_change_task_scope(pair):
    left, right = (F["CASES"][case] for case in pair)
    assert left[1:] == right[1:] and left[0] != right[0]


@pytest.mark.parametrize("html", [
    F["GOOD_GUIDE"], F["ALTERNATIVE_GUIDE"],
    F["GOOD_GUIDE"].replace("<table><caption>Port window examples</caption>", '<table aria-label="Port window examples">'),
    F["GOOD_GUIDE"].replace("Port window examples</caption>", "Port <span>window</span> examples</caption>"),
])
def test_legitimate_names_markup_and_optional_html_end_tags_are_accepted(html):
    assert F["verify_guide"](html)["ok"]


def test_nearby_heading_is_not_mistaken_for_a_table_association():
    result = F["verify_guide"](F["BAD_GUIDE"])
    assert [x["id"] for x in result["checks"] if not x["ok"]] == ["table-associated-name"]


def test_another_valid_name_does_not_mask_wrong_example_data():
    result = F["verify_guide"](F["ALTERNATIVE_GUIDE"].replace("(9,9)", "(9,10)"))
    assert [x["id"] for x in result["checks"] if not x["ok"]] == ["empty-example"]


def test_higher_priority_label_does_not_get_masked_by_an_unrelated_valid_caption():
    result = F["verify_guide"](F["GOOD_GUIDE"].replace("<table>", '<table aria-label="Different table">'))
    assert not result["ok"]


def test_another_named_table_cannot_lend_its_name_to_the_example_table():
    html = F["GOOD_GUIDE"].replace("<table><caption>Port window examples</caption>",
        '<table aria-label="Port window examples"></table><table>')
    assert not F["verify_guide"](html)["ok"]
