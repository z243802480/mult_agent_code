import json
import sys

import pytest

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.commands.review_command import ReviewCommand
from tests.integration.test_completion_verification_feedback import CHECK, call, prepare, response
from tests.integration.test_review_current_artifacts import Reviewer


def scoped(root):
    run_id, run, store = prepare(root)
    goal = store.read(run / "goal_spec.json", "goal_spec")
    goal["edit_boundary"] = {"mode": "restricted", "paths": ["src/notes_tool.py"]}
    goal["target_outputs"] = ["src/notes_tool.py"]
    store.write(run / "goal_spec.json", goal, "goal_spec")
    return run_id, run, store


class SideEffects:
    def __init__(self, outside):
        self.requests = []
        self.outside = outside

    def chat(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            commands = [call("write_file", path="src/notes_tool.py", content="VALUE = 1\n")]
            if self.outside:
                commands.append(call("run_command", command=(f'"{sys.executable}" -c "from pathlib import Path; '
                    "Path('probe-state.bin').write_text('side effect'); raise RuntimeError('probe failed')\"")))
            else:
                commands.append(call("run_tests", command=CHECK))
            return response(commands)
        return response()


@pytest.mark.parametrize("outside", [True, False])
def test_actual_effects_feedback_is_immediate_bounded_and_never_cleans_files(tmp_path, outside):
    run_id, run, _ = scoped(tmp_path)
    client = SideEffects(outside)
    result = ExecuteCommand(tmp_path, run_id=run_id, model_client=client).run()
    assert result.blocked == int(outside)
    assert result.completed == int(not outside)
    messages = [m.content for m in client.requests[1].messages if m.role == "user"]
    notices = [json.loads(m)["workspace_effect_observations"] for m in messages
               if m.startswith('{"workspace_effect_observations"')]
    assert len(notices) == int(outside)
    if outside:
        assert notices[0]["effects"][0]["path"] == "probe-state.bin"
        assert notices[0]["authorization_assessment"] == "not_determined_by_path_observation"
        assert notices[0]["generated_state_classification"] == "unassessed"
        assert notices[0]["cleanup_permission"] == "not_granted_by_observation"
        assert (tmp_path / "probe-state.bin").read_text(encoding="utf8") == "side effect"
        assert len(client.requests) <= 4  # Immediate feedback + a single final reminder, not a retry FSM.
    hooks = [json.loads(s) for s in (run / "runtime_hooks.jsonl").read_text(encoding="utf8").splitlines()]
    post = [r for r in hooks if r["hook_name"] == "post_tool_observation"]
    assert len(post) == 1
    effects = post[0]["data"]["observed_boundary_effects"]
    assert bool(effects) == outside
    if effects:
        observations = [json.loads(s) for s in (run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
        assert effects[0]["tool_call_id"] in {o["tool_call_id"] for o in observations}


class AskExecution:
    def __init__(self):
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            request_call = call("request_execution_permission", tool_name="run_tests",
                                args={"command": CHECK}, reason="Explicit consent is needed for this fixture check")
            # Pending consent must prevent every other action in this same batch too.
            return response([request_call, call("write_file", path="src/notes_tool.py", content="VALUE = 1\n"),
                             call("run_tests", command=CHECK)])
        return response()


@pytest.mark.parametrize("choice", ["approve_once", "skip"])
def test_requested_exact_execution_pauses_deduplicates_and_resumes_with_real_decision(tmp_path, choice):
    run_id, run, _ = scoped(tmp_path)
    paused = ExecuteCommand(tmp_path, run_id=run_id, model_client=AskExecution()).run()
    assert paused.blocked == 1 and not (tmp_path / "src/notes_tool.py").exists()
    assert not (run / "tool_calls.jsonl").exists()  # Intent was paused, no executed/charged tool invented.
    decisions = [json.loads(s) for s in (run / "decisions.jsonl").read_text(encoding="utf8").splitlines()]
    assert len(decisions) == 1 and decisions[0]["metadata"]["explicit_request"]
    assert CHECK in decisions[0]["question"]
    ExecuteCommand(tmp_path, run_id=run_id, model_client=AskExecution()).run()
    assert len((run / "decisions.jsonl").read_text(encoding="utf8").splitlines()) == 1
    DecideCommand(tmp_path, run_id=run_id, decision_id=decisions[0]["decision_id"], select_option_id=choice).run()
    # Resume is the real public lifecycle, not a fixture rewriting the task status.
    resumed = ResumeCommand(tmp_path, run_id=run_id, max_iterations=1,
                            execute_model_client=AskExecution()).run()
    assert resumed.applied_decisions == 1
    if choice == "skip":
        assert not (tmp_path / "src/notes_tool.py").exists()
        assert not (run / "tool_calls.jsonl").exists()
        return
    observations = [json.loads(s) for s in (run / "tool_observations.jsonl").read_text(encoding="utf8").splitlines()]
    consent = [o for o in observations if o["tool_name"] == "request_execution_permission"]
    assert len(consent) == 1 and consent[0]["ok"] == (choice == "approve_once")
    checks = [o for o in observations if o["tool_name"] == "run_tests"]
    assert checks and all(o["ok"] == (choice == "approve_once") for o in checks)
    assert not (run / "runtime_requests.jsonl").exists()  # No legacy action FSM or auto scope expansion.
    before_tools = (run / "tool_calls.jsonl").read_bytes()
    reviewer = Reviewer()
    review = ReviewCommand(tmp_path, run_id=run_id, model_client=reviewer).run()
    assert review.status == "pass"
    payload = json.loads(reviewer.requests[0].messages[-1].content)
    assert payload["current_artifacts"]["review_basis"]["observed_outside_current_edit_boundary"] == []
    assert any(f.get("content", "").strip() == "VALUE = 1" for f in payload["current_artifacts"]["files"])
    accepted = AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run()
    assert accepted.accepted
    assert json.loads((run / "run.json").read_text(encoding="utf8"))["current_phase"] == "ACCEPTED"
    assert (run / "tool_calls.jsonl").read_bytes() == before_tools
