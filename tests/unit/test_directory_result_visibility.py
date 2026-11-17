import json

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.core.agent_harness import _model_facing_payload
from tests.unit.test_review_tools import command, invoke, response, setup


@pytest.mark.parametrize("path,exists", [(".", True), ("empty", True), ("missing", False)])
def test_actual_listing_preserves_entries_and_distinguishes_missing_directory(tmp_path, path, exists):
    tools = setup(tmp_path)
    (tmp_path / "empty").mkdir()
    (tmp_path / "条件.py").write_text("# evidence\n", encoding="utf8")
    (tmp_path / ".env").write_text("protected fixture", encoding="utf8")
    observed = invoke(tools, "list_files", {"path": path})[0]
    assert observed.ok
    visible = json.loads(observed.payload)
    assert visible == {k: observed.data[k] for k in ("entries", "path_exists")}
    assert visible["path_exists"] is exists
    if path == ".":
        assert {"path": "empty", "type": "dir"} in visible["entries"]
        assert {"path": "条件.py", "type": "file"} in visible["entries"]
        assert ".env" not in observed.payload
    else:
        assert visible["entries"] == []
    tools.finish("completed")


@pytest.mark.parametrize("content,valid", [("ANSWER = 42\n", True), ("ANSWER = 41\n", False)])
def test_model_can_choose_listed_evidence_and_consume_real_check_result(tmp_path, content, valid):
    tools = setup(tmp_path, content=content)
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks/check.py").write_text(
        "from answer import ANSWER\nassert ANSWER == 42, 'observed mismatch'\n", encoding="utf8")

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            if self.count == 1:
                return response({"tool_calls": [{"tool_name": "list_files", "args": {"path": "checks"}}]})
            if self.count == 2:
                listing = next(json.loads(line) for line in request.messages[-1].text().splitlines()
                               if line.startswith('{"entries":'))
                return response({"tool_calls": [{"tool_name": "read_file", "args": {"path": listing["entries"][0]["path"]}}]})
            if self.count == 3:
                assert "observed mismatch" in request.messages[-1].text()
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command("import runpy; runpy.run_path('checks/check.py')")}}]})
            assert ("exited 0" if valid else "observed mismatch") in request.messages[-1].text()
            return response({"overall": {"status": "pass" if valid else "fail", "reason": "Executed listed evidence"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == ("pass" if valid else "fail")
    stored = json.loads(tools.path.read_text(encoding="utf8"))
    assert stored["model_requests"][1]["observations"][0]["tool_name"] == "list_files"
    assert stored["model_requests"][1]["observations"][0]["payload_included"]
    assert (tmp_path / "answer.py").read_text() == content


def test_listing_render_remains_bounded_and_legacy_paths_compatible():
    payload = _model_facing_payload("list_files", {"entries": [{"path": "x" * 200, "type": "file"}] * 500})
    assert len(payload) < 6200 and "truncated" in payload
    for name in ("list_files", "find_files", "glob"):
        assert _model_facing_payload(name, {"paths": ["one", "two"]}) == "one\ntwo"
