"""Non-production paired scope controls; no rules imported by the runtime."""

import ast
from html.parser import HTMLParser
from xml.etree.ElementTree import Element, SubElement

API_REQUEST = """Implement parse_window(value) in window.py. The input is a string with optional surrounding whitespace. After stripping that whitespace, it must contain exactly two endpoints separated by one colon; each endpoint is 1 to 5 ASCII decimal digits. Convert them to Python ints and return a tuple (start, stop) with 0 <= start <= stop <= 65535. These are half-open intervals: empty windows such as '9:9' are valid. Leading zeroes are valid within the 5-digit limit. Reject invalid types, internal whitespace, signs, non-ASCII digits, malformed or reversed ranges, and out-of-range values with ValueError. Support value as a keyword argument."""
GUIDE_REQUEST = """Publish guide.html as an HTML guide for parse_window. Include an example table with the accessible name 'Port window examples', associated using a caption, aria-label, or aria-labelledby rather than only nearby unrelated text. Include two input/result rows: '4:9' gives (4, 9), and '9:9' gives (9, 9), showing that empty half-open intervals are supported. Put the input and returned Python tuple in their respective cells; inline code markup and whitespace formatting may vary. Explanatory prose may be outside the table. Different valid HTML layouts and naming mechanisms are acceptable."""
LIMITS = """Only window.py and guide.html may change. Keep existing checks and project guidance; the project test entry in AGENTS.md must pass. Do not create extra authored files, delete data, install packages or use the network."""
GOAL = API_REQUEST + "\n" + GUIDE_REQUEST + "\n" + LIMITS
API_GOAL = API_REQUEST + "\nThis stage's acceptance conditions concern the parser API only; guide.html is supporting material and may be updated.\n" + LIMITS
GUIDE_GOAL = GUIDE_REQUEST + "\nThis stage's acceptance conditions concern the guide only; window.py supplies the example API and may be updated.\n" + LIMITS

GOOD_API = '''def parse_window(value):
    if not isinstance(value, str):
        raise ValueError("expected text")
    parts = value.strip().split(":")
    if len(parts) != 2 or any(not 1 <= len(p) <= 5 or any(c < "0" or c > "9" for c in p) for p in parts):
        raise ValueError("invalid endpoints")
    start, stop = map(int, parts)
    if start > stop or stop > 65535:
        raise ValueError("invalid interval")
    return start, stop
'''
BAD_API = GOOD_API.replace("start > stop", "start >= stop")
ALTERNATIVE_API = '''import re


def parse_window(value):
    if not isinstance(value, str):
        raise ValueError("text required")
    match = re.fullmatch(r"([0-9]{1,5}):([0-9]{1,5})", value.strip())
    if match is None:
        raise ValueError("invalid syntax")
    numbers = tuple(int(part) for part in match.groups())
    if not 0 <= numbers[0] <= numbers[1] <= 65535:
        raise ValueError("invalid bounds")
    return numbers
'''
GOOD_GUIDE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Window guide</title></head>
<body><h1>Port windows</h1><p>Endpoints form a half-open interval; equal endpoints are valid.</p>
<table><caption>Port window examples</caption>
<thead><tr><th>Input</th><th>Return value</th></tr></thead>
<tbody><tr><td><code>4:9</code></td><td><code>(4, 9)</code></td></tr>
<tr><td><code>9:9</code></td><td><code>(9, 9)</code></td></tr></tbody></table>
</body></html>
'''
BAD_GUIDE = GOOD_GUIDE.replace("<table><caption>Port window examples</caption>", "<h2>Port window examples</h2><table>")
ALTERNATIVE_GUIDE = '''<!DOCTYPE html>
<html lang="en"><title>Using windows</title><body>
<h1>Window examples</h1><p id="window-name">Port <em>window</em> examples</p>
<table aria-labelledby="window-name"><tr><th>Input<th>Result
<tr><td>4:9<td>(4,9)
<tr><td>9:9<td>(9,9)
</table><p>The stop endpoint is excluded; equal endpoints give an empty window.</p>
</body></html>
'''
STUB_API = 'def parse_window(value):\n    raise NotImplementedError\n'
STUB_GUIDE = '<!doctype html><html lang="en"><title>Window guide</title><body><p>Examples pending.</p></body></html>\n'
PROJECT_CHECKS = '''import unittest
from window import parse_window


class WindowTests(unittest.TestCase):
    def test_regular_window(self):
        self.assertEqual(parse_window("4:9"), (4, 9))

    def test_invalid_syntax(self):
        with self.assertRaises(ValueError):
            parse_window("invalid")
'''
CASES = {
    "api-alone": (API_GOAL, BAD_API, GOOD_GUIDE, False),
    "api-mixed": (GOAL, BAD_API, GOOD_GUIDE, False),
    "guide-alone": (GUIDE_GOAL, GOOD_API, BAD_GUIDE, False),
    "guide-mixed": (GOAL, GOOD_API, BAD_GUIDE, False),
    "good-mixed": (GOAL, GOOD_API, GOOD_GUIDE, True),
    "alternative-mixed": (GOAL, ALTERNATIVE_API, ALTERNATIVE_GUIDE, True),
}


def _check_cases(cases):
    results = []
    for name, check in cases:
        try:
            check()
        except Exception as exc:
            results.append({"id": name, "ok": False, "error_type": type(exc).__name__})
        else:
            results.append({"id": name, "ok": True})
    return {"ok": all(x["ok"] for x in results), "count": len(results), "checks": results}


def verify_api(parse_window):
    def valid(text, expected):
        result = parse_window(value=text)
        assert type(result) is tuple and result == expected and all(type(n) is int for n in result)

    def invalid(value):
        try:
            parse_window(value=value)
        except ValueError:
            return
        raise AssertionError("ValueError required")

    accepted = [("ordinary", "4:9", (4, 9)), ("empty", "9:9", (9, 9)),
                ("minimum-empty", "0:0", (0, 0)), ("maximum-empty", "65535:65535", (65535, 65535)),
                ("bounds", "0:65535", (0, 65535)), ("leading-zeroes", "00004:00009", (4, 9)),
                ("outer-whitespace", " \t4:9\n", (4, 9))]
    rejected = [("reversed", "9:4"), ("negative", "-1:9"), ("too-large", "0:65536"),
                ("endpoint-length", "000000:1"), ("decimal", "4.0:9"),
                ("inner-left-space", "4 :9"), ("inner-right-space", "4: 9"),
                ("empty-endpoint", "4:"), ("extra-colon", "4:9:12"),
                ("non-ascii", "４:９"), ("missing", ""), ("bool", True),
                ("integer", 4), ("none", None)]
    return _check_cases([(name, lambda text=text, expected=expected: valid(text, expected))
                         for name, text, expected in accepted] +
                        [(name, lambda value=value: invalid(value)) for name, value in rejected])


class _Document(HTMLParser):
    """Static associations only; not an HTML5 renderer or accessibility-tree audit."""

    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(content)
        self.close()

    def _end(self, tags):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag in tags:
                del self.stack[index:]
                return

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._end({"tr"})
        elif tag in {"td", "th"}:
            self._end({"td", "th"})
        element = SubElement(self.stack[-1], tag, {k: v or "" for k, v in attrs})
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        self._end({tag})

    def handle_data(self, data):
        parent = self.stack[-1]
        if len(parent):
            parent[-1].tail = (parent[-1].tail or "") + data
        else:
            parent.text = (parent.text or "") + data


def _text(element):
    return " ".join("".join(element.itertext()).split())


def verify_guide(content):
    document = _Document(content).root
    tables = list(document.iter("table"))
    ids = {}
    for node in document.iter():
        if node.get("id"):
            ids.setdefault(node.get("id"), []).append(node)

    def name(table):
        references = table.get("aria-labelledby", "").split()
        if references and any(key in ids for key in references):
            assert all(len(ids.get(key, [])) == 1 for key in references)
            return " ".join(_text(ids[key][0]) for key in references)
        if table.get("aria-label", "").strip():
            return " ".join(table.get("aria-label").split())
        caption = table.find("caption")
        return _text(caption) if caption is not None else ""

    def named_table():
        assert any(name(table) == "Port window examples" for table in tables)

    def has_example(table, text, expected):
        for row in table.iter("tr"):
            cells = [node for node in row if node.tag in {"td", "th"}]
            if len(cells) == 2 and _text(cells[0]) == text:
                try:
                    value = ast.literal_eval(_text(cells[1]))
                except (ValueError, SyntaxError):
                    continue
                if type(value) is tuple and value == expected:
                    return True
        return False

    def example(text, expected):
        assert any(has_example(table, text, expected) for table in tables)

    def same_table():
        named = [table for table in tables if name(table) == "Port window examples"]
        examples = [("4:9", (4, 9)), ("9:9", (9, 9))]
        if not named or not all(any(has_example(table, text, value) for table in tables) for text, value in examples):
            return  # Missing primary facts are reported by their own checks above.
        assert any(all(has_example(table, text, value) for text, value in examples) for table in named)

    return _check_cases([("table-associated-name", named_table),
                         ("ordinary-example", lambda: example("4:9", (4, 9))),
                         ("empty-example", lambda: example("9:9", (9, 9))),
                         ("examples-belong-to-named-table", same_table)])


def verify(parse_window, guide):
    api, documentation = verify_api(parse_window), verify_guide(guide)
    return {"ok": api["ok"] and documentation["ok"], "api": api, "guide": documentation,
            "count": api["count"] + documentation["count"]}
