"""Fresh-process evidence/cost continuity, using deterministic model doubles only."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.workflow

WORKER = r"""
import json, os, subprocess, sys
from pathlib import Path
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.models.fake import FakeModelClient

sys.stdout.reconfigure(encoding='utf-8')
root, phase = Path(sys.argv[1]), sys.argv[2]
check = '"' + sys.executable + '" -c "import checkpoint; assert checkpoint.VALUE == 41"'

class Client:
    def __init__(self):
        self.turns = 0
        self.fallback = FakeModelClient()

    def chat(self, request):
        if request.purpose == 'goal_spec':
            data = json.loads(self.fallback.chat(request).content)
            data['target_outputs'] = ['checkpoint.py']
            data['expanded_requirements'][0]['expected_artifacts'] = ['checkpoint.py']
            data['verification_strategy'] = [check]
        elif request.purpose == 'task_planning':
            data = {'tasks': [{
                'task_id': 'task-0001', 'title': 'Create and verify checkpoint module',
                'description': 'Create checkpoint.py with VALUE 41 and validate its runtime value.',
                'task_kind': 'implementation', 'priority': 'high', 'depends_on': [],
                'acceptance': ['checkpoint.py has VALUE 41 and its declared validation passes'],
                'expected_artifacts': ['checkpoint.py'],
                'expected_changed_files': ['checkpoint.py'], 'validation_commands': [check],
            }]}
        elif request.purpose == 'task_execution':
            self.turns += 1
            if phase == 'start' and self.turns == 1:
                # The real CLI writes the normal pause signal after the loop's
                # turn-start check. This batch must still finish before pausing.
                subprocess.run([sys.executable, '-m', 'asteria_runtime', 'pause',
                                '--root', str(root), '--session-id', request.metadata['run_id']],
                               check=True, capture_output=True, timeout=15)
                data = {'narration': 'Create durable artifact before pause', 'done': False,
                        'tool_calls': [{'tool_name': 'write_file', 'args': {
                            'path': 'checkpoint.py', 'content': 'VALUE = 41\n'}}]}
            elif phase == 'resume' and self.turns == 1:
                data = {'narration': 'Only validation remains', 'done': False, 'tool_calls': [
                    {'tool_name': 'read_file', 'args': {'path': 'checkpoint.py'}},
                    {'tool_name': 'run_tests', 'args': {'command': check}},
                ]}
            else:
                data = {'narration': 'Verification is complete', 'done': True, 'tool_calls': []}
        else:
            return self.fallback.chat(request)
        return ChatResponse(json.dumps(data), 'stop', TokenUsage(10, 20, 30),
                            'fake', 'cross-process-fixture', {})

client = Client()
if phase == 'start':
    InitCommand(root).run()
    path = root / '.asteria/policies.json'
    policy = json.loads(path.read_text(encoding='utf-8'))
    # Isolate one task attempt; these are fixture overrides, not new product defaults.
    policy.setdefault('agent_loop', {}).update(
        auto_repair=False, auto_replan=False, auto_replan_goal=False,
        auto_continue=False, auto_accept=False)
    path.write_text(json.dumps(policy), encoding='utf-8')
    result = RunCommand(root, 'Create checkpoint.py with VALUE 41 and verify it',
                        model_client=client, plan_model_client=client,
                        execute_model_client=client, review_model_client=client,
                        permission_level='auto', enable_research=False).run()
else:
    result = ResumeCommand(root, run_id=sys.argv[3], model_client=client,
                           execute_model_client=client, review_model_client=client).run()
print(json.dumps({'pid': os.getpid(), 'run_id': result.run_id, 'status': result.status}))
"""


def invoke(root: Path, phase: str, run_id: str = "") -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        "PYTHONUTF8": "1",
        "ASTERIA_HOME": str(root / "isolated-home"),
        "AGENT_MODEL_PROVIDER": "fake",
        "AGENT_MODEL_STRONG_PROVIDER": "fake",
        "AGENT_MODEL_CHEAP_PROVIDER": "fake",
    }
    result = subprocess.run(
        [sys.executable, "-c", WORKER, str(root), phase, run_id],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("corrupt", [False, True])
def test_same_run_fresh_process_resume_keeps_written_artifact_and_budget(
    tmp_path: Path,
    corrupt: bool,
) -> None:
    initial = invoke(tmp_path, "start")
    assert initial["status"] == "paused"
    artifact = tmp_path / "checkpoint.py"
    assert artifact.read_text(encoding="utf-8") == "VALUE = 41\n"
    run = tmp_path / ".asteria/runs" / initial["run_id"]
    goal_before = (run / "goal_spec.json").read_bytes()
    names = ["model_calls.jsonl", "tool_calls.jsonl", "tool_observations.jsonl"]
    prefixes = {name: (run / name).read_bytes() for name in names}
    cost_before = json.loads((run / "cost_report.json").read_text(encoding="utf-8"))
    if corrupt:
        artifact.write_text("VALUE = 0\n", encoding="utf-8")

    resumed = invoke(tmp_path, "resume", initial["run_id"])
    assert resumed["pid"] != initial["pid"]
    assert resumed["run_id"] == initial["run_id"]
    assert len(list((tmp_path / ".asteria/runs").glob("run-*"))) == 1
    assert (run / "goal_spec.json").read_bytes() == goal_before
    for name, prefix in prefixes.items():
        assert (run / name).read_bytes().startswith(prefix)
    calls = [
        json.loads(line)
        for line in (run / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cost_after = json.loads((run / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_after["model_calls"] > cost_before["model_calls"]
    assert cost_after["model_calls"] == len(calls)
    assert cost_after["estimated_input_tokens"] == sum(c.get("input_tokens", 0) or 0 for c in calls)
    assert cost_after["estimated_output_tokens"] == sum(
        c.get("output_tokens", 0) or 0 for c in calls
    )
    tools = [
        json.loads(line)
        for line in (run / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sum(t["tool_name"] == "write_file" for t in tools) == 1
    assert any(t["tool_name"] == "run_tests" for t in tools)
    assert (resumed["status"] == "completed") is not corrupt
    if not corrupt:
        assert sum(c["purpose"] == "task_execution" for c in calls) == 3
        assert not list((run / "task_pause_checkpoints").glob("*.json"))
