"""Non-production Review evaluation data; never a runtime rule or model instruction."""

from copy import deepcopy

GOAL = """Implement aggregate(rows, *, region=None) in aggregate.py. Accept a one-pass iterable of dictionaries. Each row must initially have enabled as an exact bool. Ignore disabled rows before accessing or validating any other field. For enabled rows, region must be a nonblank string, preserving spelling and case. If a region filter is supplied, ignore other regions before accessing or validating sku or qty. The filter itself must be None or a nonblank string. For included rows, sku must be a nonblank string and qty an exact Python int greater than zero, excluding bool and float. Merge quantities by SKU in first-seen order; preserve SKU spelling and case. Return a new list of new dictionaries containing only sku and qty, ignore extra fields, and never mutate input rows, including on later failure. Invalid row shapes or required values and noniterable input raise ValueError. Empty selection returns a new empty list. Support the documented parameter names as keyword arguments.
Only aggregate.py may change. Keep all existing project checks and guidance. Final verification includes the project test entry in AGENTS.md. Do not create extra authored files, delete data, install dependencies or use the network."""

GOOD = '''def aggregate(rows, *, region=None):
    if region is not None and (not isinstance(region, str) or not region.strip()):
        raise ValueError("invalid filter")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError("rows must be iterable") from exc
    totals = {}
    for row in iterator:
        if not isinstance(row, dict) or type(row.get('enabled')) is not bool:
            raise ValueError("invalid row or enabled")
        if not row['enabled']:
            continue
        area = row.get('region')
        if not isinstance(area, str) or not area.strip():
            raise ValueError("invalid region")
        if region is not None and area != region:
            continue
        sku, qty = row.get('sku'), row.get('qty')
        if not isinstance(sku, str) or not sku.strip() or type(qty) is not int or qty <= 0:
            raise ValueError("invalid sku or qty")
        totals[sku] = totals.get(sku, 0) + qty
    return [dict(sku=sku, qty=qty) for sku, qty in totals.items()]
'''

BAD_DISABLED = GOOD.replace(
    "        if not row['enabled']:\n            continue\n", "",
).replace("        sku, qty =", "        if not row['enabled']:\n            continue\n        sku, qty =")

BAD_REGION = GOOD.replace(
    "        if region is not None and area != region:\n            continue\n", "",
).replace("        totals[sku] =", "        if region is not None and area != region:\n            continue\n        totals[sku] =")

ALTERNATIVE = '''def _selected(values, region):
    for value in values:
        if not isinstance(value, dict) or type(value.get("enabled")) != bool:
            raise ValueError("invalid row")
        if value["enabled"] is False:
            continue
        area = value.get("region")
        if not isinstance(area, str) or area.strip() == "":
            raise ValueError("invalid region")
        if region is None or area == region:
            yield value


def aggregate(rows, *, region=None):
    if region is not None:
        if not isinstance(region, str) or region.strip() == "":
            raise ValueError("invalid filter")
    try:
        values = iter(rows)
    except TypeError as exc:
        raise ValueError("not iterable") from exc
    result, positions = [], {}
    for item in _selected(values, region):
        key, amount = item.get("sku"), item.get("qty")
        if not isinstance(key, str) or not key.strip() or type(amount) != int or amount < 1:
            raise ValueError("invalid payload")
        if key in positions:
            result[positions[key]]["qty"] += amount
        else:
            positions[key] = len(result)
            result.append({"sku": key, "qty": amount})
    return result
'''

PROJECT_CHECKS = '''import unittest
from aggregate import aggregate


class AggregateTests(unittest.TestCase):
    def test_merge(self):
        rows = [dict(enabled=True, region="east", sku="a", qty=1),
                dict(enabled=True, region="east", sku="a", qty=2)]
        self.assertEqual(aggregate(rows), [dict(sku="a", qty=3)])

    def test_filter(self):
        rows = [dict(enabled=True, region="east", sku="a", qty=1),
                dict(enabled=True, region="west", sku="b", qty=2)]
        self.assertEqual(aggregate(rows, region="east"), [dict(sku="a", qty=1)])
'''

STUB = 'def aggregate(rows, *, region=None):\n    raise NotImplementedError\n'
VARIANTS = {"bad-disabled": BAD_DISABLED, "bad-region": BAD_REGION, "good": GOOD, "alternative": ALTERNATIVE}


def verify(aggregate):
    """Behavioral checks, independent of source layout/imports/helper names."""
    results = []

    def case(name, check):
        try:
            check()
        except Exception as exc:
            results.append({"id": name, "ok": False, "error_type": type(exc).__name__})
        else:
            results.append({"id": name, "ok": True})

    def equal(rows, expected, **kwargs):
        assert aggregate(rows=rows, **kwargs) == expected

    def invalid(rows, **kwargs):
        try:
            aggregate(rows=rows, **kwargs)
        except ValueError:
            return
        raise AssertionError("Expected ValueError")

    def row(**updates):
        return {"enabled": True, "region": "east", "sku": "a", "qty": 2, **updates}

    case("disabled-missing-payload", lambda: equal([{"enabled": False}], []))
    case("disabled-invalid-region", lambda: equal([row(enabled=False, region=None)], []))
    case("unselected-invalid-quantity", lambda: equal([row(region="west", qty=False)], [], region="east"))
    case("unselected-missing-payload", lambda: equal([{"enabled": True, "region": "west"}], [], region="east"))

    class GuardedRow(dict):
        def __init__(self, values, forbidden):
            super().__init__(values)
            self.forbidden = forbidden

        def get(self, key, *args):
            assert key not in self.forbidden, "Ignored payload was accessed"
            return super().get(key, *args)

        def __getitem__(self, key):
            assert key not in self.forbidden, "Ignored payload was accessed"
            return super().__getitem__(key)

    case("disabled-payload-not-accessed", lambda: equal(
        [GuardedRow({"enabled": False}, {"region", "sku", "qty"})], []))
    case("unselected-payload-not-accessed", lambda: equal(
        [GuardedRow({"enabled": True, "region": "west"}, {"sku", "qty"})], [], region="east"))
    case("enabled-strict-bool", lambda: invalid([row(enabled=1)]))
    case("enabled-required-even-unselected", lambda: invalid([{"region": "west"}], region="east"))
    case("enabled-region-required", lambda: invalid([row(region=" ")]))
    case("included-sku-required", lambda: invalid([row(sku=" ")]))
    case("included-quantity-not-bool", lambda: invalid([row(qty=True)]))
    case("included-quantity-not-float", lambda: invalid([row(qty=2.0)]))
    case("included-quantity-positive", lambda: invalid([row(qty=0)]))
    case("invalid-row-shape", lambda: invalid([None]))
    case("noniterable-input", lambda: invalid(None))
    case("filter-type", lambda: invalid([], region=1))
    case("filter-nonblank", lambda: invalid([], region=" "))
    case("first-seen-merge-spelling", lambda: equal([row(sku=" B "), row(sku="a"), row(sku=" B ")],
          [{"sku": " B ", "qty": 4}, {"sku": "a", "qty": 2}]))
    case("region-exact-spelling", lambda: equal([row(region="East"), row()], [{"sku": "a", "qty": 2}], region="East"))
    case("one-pass-keyword-api", lambda: equal((x for x in [row(), row()]), [{"sku": "a", "qty": 4}], region="east"))

    def unchanged():
        values = [row(extra={"nested": [1]}), row()]
        before = deepcopy(values)
        result = aggregate(values)
        assert values == before and result == [{"sku": "a", "qty": 4}]
        assert result[0] is not values[0] and result[0] is not values[1]
        result[0]["qty"] = 100
        assert values == before
        invalid(values + [row(qty=-1)])
        assert values == before

    case("new-objects-extra-fields-and-nonmutation", unchanged)

    def empty():
        values = []
        result = aggregate(values)
        assert result == [] and result is not values

    case("empty-new-result", empty)
    return {"ok": all(r["ok"] for r in results), "count": len(results), "checks": results}
