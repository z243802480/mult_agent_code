"""Real Execute/Replan boundaries with deterministic model decisions and real tools."""

import json
from pathlib import Path
import sys

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.integration.test_execute_command import FakePlanClient


CHECK = (f'"{sys.executable}" -c "from pathlib import Path; '
         "assert Path('src/notes_tool.py').read_text().strip() == 'VALUE = 1'\"")
OTHER = f'"{sys.executable}" -c "print(123)"'


def response(calls=()):
    return ChatResponse(content=json.dumps({'narration': 'Check current evidence.',
        'tool_calls': list(calls), 'done': not calls}), finish_reason='stop',
        usage=TokenUsage(1, 1, 2), model_provider='fake', model_name='feedback-fixture', raw_response={})


def call(name, **args):
    return {'tool_name': name, 'args': args}


class FeedbackClient:
    def __init__(self, *, repair=False, fixes_artifact=True):
        self.requests = []
        self.repair = repair
        self.fixes_artifact = fixes_artifact

    def chat(self, request):
        self.requests.append(request)
        turn = len(self.requests)
        if turn == 1:
            return response([call('write_file', path='src/notes_tool.py', content='VALUE = 0\n'),
                             call('run_tests', command=CHECK)])
        if turn == 2:
            value = int(self.fixes_artifact)
            return response([call('write_file', path='src/notes_tool.py', content=f'VALUE = {value}\n'),
                             call('run_command', command=OTHER)])
        if turn == 4 and self.repair:
            assert any(json.dumps(CHECK) in message.content and 'latest' in message.content
                       for message in request.messages if message.role == 'user')
            return response([call('run_tests', command=CHECK)])
        return response()


def prepare(root):
    InitCommand(root).run()
    plan = PlanCommand(root, 'create a tiny notes tool', model_client=FakePlanClient()).run()
    store = JsonStore(SchemaValidator(Path('schemas')))
    run = root / '.asteria/runs' / plan.run_id
    board = store.read(run / 'task_plan.json', 'task_board')
    board['tasks'][0].update({'expected_artifacts': ['src/notes_tool.py'],
        'expected_changed_files': ['src/notes_tool.py'], 'write_scope': ['src/notes_tool.py'],
        'validation_commands': [], 'verification_policy': {'required': True, 'commands': []}})
    store.write(run / 'task_plan.json', board, 'task_board')
    return plan.run_id, run, store


@pytest.mark.parametrize('repair', [True, False])
def test_unclosed_command_is_fed_back_in_same_task_once_per_observed_failure(tmp_path, repair):
    run_id, run, store = prepare(tmp_path)
    client = FeedbackClient(repair=repair)
    result = ExecuteCommand(tmp_path, run_id=run_id, model_client=client).run()
    assert result.completed == int(repair)
    assert result.blocked == int(not repair)
    assert len(client.requests) == (5 if repair else 4)
    board = store.read(run / 'task_plan.json', 'task_board')
    assert len(board['tasks']) == 1
    rows = [json.loads(x) for x in (run / 'user_progress.jsonl').read_text(encoding='utf8').splitlines()]
    held = [x for x in rows if (x.get('data') or {}).get('unresolved_verification_commands')]
    assert len(held) == 1
    assert held[0]['data']['unresolved_verification_commands'] == [CHECK]


@pytest.mark.parametrize('correct_artifact', [True, False])
def test_repair_rechecks_pinned_failure_without_forcing_a_new_diff(tmp_path, correct_artifact):
    run_id, run, store = prepare(tmp_path)
    first = ExecuteCommand(tmp_path, run_id=run_id,
        model_client=FeedbackClient(fixes_artifact=correct_artifact)).run()
    assert first.blocked == 1
    ReplanCommand(tmp_path, run_id=run_id).run()
    task = store.read(run / 'task_plan.json', 'task_board')['tasks'][-1]
    assert task['verified_noop_allowed']
    assert CHECK in task['validation_commands']
    before = (tmp_path / 'src/notes_tool.py').read_bytes()
    before_cost = store.read(run / 'cost_report.json', 'cost_report')

    class OnlyOtherGreen:
        def __init__(self):
            self.calls = 0

        def chat(self, request):
            self.calls += 1
            return response([call('run_command', command=OTHER)]) if self.calls == 1 else response()

    result = ExecuteCommand(tmp_path, run_id=run_id, model_client=OnlyOtherGreen()).run()
    assert result.completed == int(correct_artifact)
    assert result.blocked == int(not correct_artifact)
    assert (tmp_path / 'src/notes_tool.py').read_bytes() == before
    assert store.read(run / 'cost_report.json', 'cost_report')['tool_calls'] > before_cost['tool_calls']
    evidence = [json.loads(x) for x in (run / 'task_execution_evidence.jsonl').read_text(encoding='utf8').splitlines()]
    assert evidence[-1]['contract_check']['changed_files'] == []
    pinned = [x for x in evidence[-1]['verification_results'] if x.get('requested_command') == CHECK]
    assert pinned and all(x['ok'] == correct_artifact for x in pinned)
