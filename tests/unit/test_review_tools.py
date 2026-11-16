import json
from pathlib import Path
import sys

import pytest

from asteria_runtime.agents.review_agent import ReviewAgent
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.model_driven_turn import execute_tool_calls
from asteria_runtime.core.policy_config import merge_policy_defaults
from asteria_runtime.core.review_artifacts import collect_review_artifacts
from asteria_runtime.core.review_tools import ReviewTools
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


def response(value, finish="stop"):
    return ChatResponse(content=json.dumps(value), finish_reason=finish, usage=TokenUsage(1, 1, 2),
                        model_provider="fake", model_name="review-tools", raw_response={})


def command(code):
    return f'"{sys.executable}" -c "{code}"'


def setup(root, *, content="ANSWER = 41\n", **kwargs):
    root = root.resolve()
    validator = SchemaValidator(Path("schemas"))
    policy = merge_policy_defaults({})
    policy["permissions"]["allow_shell"] = True
    policy["permission_mode"] = "auto"
    (root / "answer.py").write_text(content, encoding="utf8")
    ctx = RuntimeContext(root, "run-review", policy, validator, budget=BudgetController(policy, "run-review"))
    goal = {"target_outputs": ["answer.py"]}
    artifacts = collect_review_artifacts(ctx, goal, {})
    return ReviewTools(ctx, artifacts, goal, {}, **kwargs)


def invoke(tools, name, args):
    return execute_tool_calls(tools, [{"tool_name": name, "args": args}], tools.task, tools.context)


def test_selected_failing_executable_result_reaches_model_and_preserves_source(tmp_path):
    tools = setup(tmp_path)
    original = (tmp_path / "answer.py").read_bytes()

    class Model:
        requests = []

        def chat(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                payload = json.loads(request.messages[1].text())
                assert payload["review_tools"]["is_os_sandbox"] is False
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command("from answer import ANSWER; assert ANSWER == 42, 'independent failure'")}}]})
            feedback = request.messages[-1].text()
            assert "independent failure" in feedback and "exited 1" in feedback
            return response({"overall": {"status": "fail", "score": 0, "reason": "Independent assertion fails"}})

    model = Model()
    report = ReviewAgent(model, tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == "fail"
    assert len(model.requests) == 2
    assert (tmp_path / "answer.py").read_bytes() == original
    assert not (tmp_path / "__pycache__").exists()
    evidence = json.loads(tools.path.read_text(encoding="utf8"))
    assert len(evidence["observations"]) == 1 and evidence["observations"][0]["ok"] is False
    assert evidence["observations"][0]["observation_id"]
    assert tools.context.budget.cost_report()["tool_calls"] == 1
    assert not tools.copy_context.root.exists()


@pytest.mark.parametrize("name,args", [
    ("write_file", {"path": "answer.py", "content": "forged"}),
    ("apply_patch", {"patch": "forged"}), ("restore_backup", {"backup_id": "forged"}),
    ("mcp__remote", {}), ("skill__execute", {}), ("spawn_agent", {}),
    ("run_command", {"command": "echo forbidden surface"}),
    ("read_file", {"path": ".env"}),
    ("run_tests", {"command": "git push"}),
    ("run_tests", {"command": "curl https://example.com"}),
    ("run_tests", {"command": "python -m pip install unwanted"}),
    ("run_tests", {"command": "rm answer.py"}),
])
def test_denied_check_never_grants_permission_or_modifies_source(tmp_path, name, args):
    tools = setup(tmp_path)
    tools.context.policy["permissions"]["allow_network"] = False
    observations = invoke(tools, name, args)
    assert observations and not observations[0].ok
    evidence = tools.finish("completed")
    assert evidence["errors"]
    assert (tmp_path / "answer.py").read_text() == "ANSWER = 41\n"
    assert not (tools.context.run_dir / "decisions.jsonl").exists()


def test_copy_never_opens_protected_files_or_links_and_does_not_promote_generated_files(tmp_path, monkeypatch):
    tools = setup(tmp_path)
    for path in [".env", "nested/.env.local", "secrets/token", "nested/secrets/token", "private.key", ".git/HEAD"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("DO NOT READ")
    original = Path.open

    def checked(path, *args, **kwargs):
        assert path.name not in {".env", ".env.local", "token", "private.key", "HEAD"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    assert invoke(tools, "run_tests", {"command": command("from pathlib import Path; Path('probe.tmp').write_text('temporary'); print('probe ran')")})[0].ok
    root = tools.copy_context.root
    assert (root / "probe.tmp").exists() and not (tmp_path / "probe.tmp").exists()
    assert not (root / ".env").exists() and not (root / ".git").exists()
    assert tools.finish("completed")["errors"] == []


def test_modified_copied_inputs_cannot_be_reported_as_original_artifact_verification(tmp_path):
    tools = setup(tmp_path)
    assert invoke(tools, "run_tests", {"command": command("from pathlib import Path; Path('answer.py').write_text('ANSWER = 42')")})[0].ok
    evidence = tools.finish("completed")
    assert evidence["errors"] == ["copied_input_changed:answer.py"]
    assert (tmp_path / "answer.py").read_text() == "ANSWER = 41\n"


@pytest.mark.parametrize("option", [{"max_files": 0}, {"max_bytes": 1}, {"total_seconds": 0}])
def test_copy_limits_fail_closed_before_any_command(tmp_path, option):
    tools = setup(tmp_path, **option)
    assert not invoke(tools, "run_tests", {"command": command("raise RuntimeError('MUST NOT RUN')")})[0].ok
    evidence = tools.finish("budget_exhausted")
    assert evidence["errors"] and not evidence["copy_created"]
    assert tools.context.budget.cost_report()["tool_calls"] == 0


def test_artifact_changed_before_copy_is_not_verified_as_old_snapshot(tmp_path):
    tools = setup(tmp_path)
    (tmp_path / "answer.py").write_text("ANSWER = 42\n")
    assert not invoke(tools, "run_tests", {"command": command("print('MUST NOT RUN')")})[0].ok
    evidence = tools.finish("completed")
    assert evidence["errors"] and tools.context.budget.cost_report()["tool_calls"] == 0


def test_ask_everything_does_not_implicitly_allow_read_or_shell(tmp_path):
    tools = setup(tmp_path)
    tools.context.policy["permission_mode"] = "ask_everything"
    tools.allowed.clear()
    assert not invoke(tools, "read_file", {"path": "answer.py"})[0].ok
    assert tools.finish("completed")["errors"] == ["selected_check_denied:ask_everything"]
    assert tools._temporary is None


def test_symlink_is_not_copied_or_followed(tmp_path):
    tools = setup(tmp_path)
    outside = tmp_path.parent / "outside-review-target"
    outside.write_text("must not be read")
    try:
        (tmp_path / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert invoke(tools, "read_file", {"path": "answer.py"})[0].ok
    assert not (tools.copy_context.root / "link").exists()
    assert tools.finish("completed")["errors"] == []


def test_iteration_fuse_and_permission_denial_cannot_turn_into_pass(tmp_path):
    tools = setup(tmp_path)

    class Model:
        def chat(self, request):
            return response({"tool_calls": [{"tool_name": "read_file", "args": {"path": "answer.py"}}]})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == "partial"
    assert tools.model_calls == 8
    assert report["trajectory_eval"]["review_assessment"]["status"] == "unavailable"


def test_no_tool_selection_is_recorded_without_fabricating_execution(tmp_path):
    tools = setup(tmp_path)

    class Model:
        def chat(self, request):
            return response({"overall": {"status": "pass", "score": 1, "reason": "Inspected supplied evidence"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == "pass"
    evidence = json.loads(tools.path.read_text(encoding="utf8"))
    assert evidence["observations"] == [] and not evidence["copy_created"]
    assert tools.context.budget.cost_report()["tool_calls"] == 0


@pytest.mark.parametrize("failure", ["timeout", "denied", "copied_input_changed"])
def test_report_cannot_waive_unexecuted_or_changed_input_boundary(tmp_path, failure):
    tools = setup(tmp_path)
    if failure == "denied":
        tools.context.policy["permissions"]["allow_shell"] = False
    code = "import time; time.sleep(10)" if failure == "timeout" else (
        "from pathlib import Path; Path('answer.py').write_text('ANSWER = 42')"
        if failure == "copied_input_changed" else "print('denied')")

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            if self.count == 1:
                return response({"tool_calls": [{"tool_name": "run_tests", "args": {
                    "command": command(code), "timeout_seconds": 0.1 if failure == "timeout" else 30}}]})
            return response({"overall": {"status": "pass", "score": 1, "reason": "Cannot waive evidence boundary"}})

    report = ReviewAgent(Model(), tools.context.validator, tools).evaluate({}, "run-review")
    assert report["overall"]["status"] == "partial"
    assert report["trajectory_eval"]["review_validation"]["errors"]


@pytest.mark.parametrize("when", ["before_model", "after_model"])
def test_shared_goal_hard_stop_prevents_model_or_its_proposed_command(tmp_path, when):
    tools = setup(tmp_path)

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            tools.context.budget.usage.model_calls = 10000
            return response({"tool_calls": [{"tool_name": "run_tests", "args": {"command": "echo MUST_NOT_RUN"}}]})

    if when == "before_model":
        tools.context.budget.usage.model_calls = 10000
    model = Model()
    report = ReviewAgent(model, tools.context.validator, tools).evaluate({}, "run-review")
    assert model.count == (0 if when == "before_model" else 1)
    assert report["overall"]["status"] == "partial"
    assert tools.context.budget.cost_report()["tool_calls"] == 0
    assert tools._temporary is None


def test_provider_failure_after_execution_does_not_replay_tools_on_another_tier(tmp_path):
    tools = setup(tmp_path)

    class Model:
        count = 0

        def chat(self, request):
            self.count += 1
            if self.count == 1:
                return response({"tool_calls": [{"tool_name": "read_file", "args": {"path": "answer.py"}}]})
            raise RuntimeError("provider unavailable after tool")

    model = Model()
    report = ReviewAgent(model, tools.context.validator, tools).evaluate({}, "run-review")
    assert model.count == 2 and report["overall"]["status"] == "partial"
    evidence = json.loads(tools.path.read_text(encoding="utf8"))
    assert len(evidence["observations"]) == 1 and evidence["observations"][0]["ok"]
    assert tools.context.budget.cost_report()["tool_calls"] == 1


def test_read_aliases_and_paged_content_remain_available_in_copy(tmp_path):
    tools = setup(tmp_path)
    names = {tool["name"] for tool in tools.describe()["tools"]}
    assert names == {"read_file", "list_files", "glob", "grep", "run_tests"}
    for name, args in [("read_file", {"path": "answer.py"}), ("glob", {"pattern": "*.py"}),
                       ("grep", {"pattern": "ANSWER", "path": "."}), ("list_files", {})]:
        observed = invoke(tools, name, args)
        assert observed[0].ok, observed[0].summary
    assert tools.finish("completed")["errors"] == []


def test_review_remaining_time_never_increases_existing_role_deadline(tmp_path):
    from asteria_runtime.models.base import ChatRequest
    tools = setup(tmp_path)

    class Model:
        def chat(self, request):
            assert request.timeout_seconds == 3 and request.metadata["deadline_ms"] == 3000
            return response({})

    tools.bounded_client(Model()).chat(ChatRequest(purpose="run_review", model_tier="strong", messages=[],
                                                  metadata={"deadline_ms": 3000}))
    tools.finish("completed")
