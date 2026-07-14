import json
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Lock

import pytest

from asteria_runtime.commands.execute_command import (
    ExecuteCommand,
    _methodology_stop_guardrail_decision,
    _methodology_turn_start_decision,
)
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.agent_tool_surface import model_tool_surface
from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

pytestmark = pytest.mark.workflow


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a tiny notes tool",
                    "normalized_goal": "Create a tiny notes tool",
                    "goal_type": "software_tool",
                    "assumptions": ["local files are acceptable"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Create a notes module with a simple add function",
                            "source": "inferred",
                            "acceptance": ["a module file exists"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["module exists"],
                    "verification_strategy": ["run a command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class ExplodingPlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError("provider unavailable")


class FakeExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        if request.worker_transport == "tool_use":
            return ChatResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(15, 25, 40),
                model_provider="fake",
                model_name="fake-execute",
                raw_response=_tool_use_raw_response(
                    [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                        },
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\"",
                            },
                        },
                    ]
                ),
            )
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create notes module and verify Python can import it.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "verify the module behavior",
                        }
                    ],
                    "completion_notes": "src/notes_tool.py contains a working add_note function",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class ExplodingExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise AssertionError("model should not be called when delegation quality gate blocks")


class FakeReadonlyExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-readonly")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Run readonly verification without modifying files.",
                    "tool_calls": [],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": 'python -c "assert True"'},
                            "reason": "readonly verification",
                        }
                    ],
                    "completion_notes": "readonly task verified",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-readonly-execute",
            raw_response={},
        )


def _tool_use_raw_response(tool_calls: list[dict]) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{index + 1}",
                            "type": "function",
                            "function": {
                                "name": call["tool_name"],
                                "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                            },
                        }
                        for index, call in enumerate(tool_calls)
                    ],
                }
            }
        ]
    }


class FakeSubagentExecuteClient:
    def __init__(self) -> None:
        self.calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest_observation = runtime_context.get("latest_agent_loop_observation") or {}
        if latest_observation:
            self.latest_observations.append(latest_observation)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if runtime_context.get("subagent_worker"):
            tool_calls = [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "src/notes_tool.py",
                        "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                        "overwrite": True,
                    },
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                    },
                },
            ]
            if request.worker_transport == "tool_use":
                return ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    usage=TokenUsage(5, 8, 13),
                    model_provider="fake",
                    model_name="fake-subagent-execute",
                    raw_response=_tool_use_raw_response(tool_calls),
                )
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Child subagent creates notes module and verifies it.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": tool_calls[0]["args"],
                        "reason": "create delegated artifact",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": tool_calls[1]["args"],
                        "reason": "verify delegated artifact",
                    }
                ],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "The child worker should implement and verify the artifact.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {"summary": "Child tool execution succeeds."},
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "child worker completed",
            }
        elif latest_observation:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after successful subagent worker observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "The subagent worker completed and verified the task.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {
                            "summary": "Runtime records stop after subagent completion."
                        },
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [latest_observation["observation_id"]],
                    }
                },
                "completion_notes": "parent loop stopped",
            }
        else:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Delegate this task to a subagent.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "schema_version": "0.1.0",
                    "decision_id": "agent-loop-decision-0001",
                    "run_id": "run-placeholder",
                    "task_id": task_id,
                    "created_at": "2026-05-29T10:00:00+08:00",
                    "next_action": {
                        "action": "subagent",
                        "reason": "Independent implementation should be delegated.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "subagent", "name": "subagent"},
                        "expected_observation": {
                            "summary": "Subagent worker completes the delegated task.",
                            "success_signal": "worker evidence is present",
                            "parallel_safety": "serial",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
                        "evidence_refs": [],
                    },
                },
                "completion_notes": "subagent dispatch requested",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-subagent-execute",
            raw_response={},
        )


class FakeSubagentMultiRoundExecuteClient:
    def __init__(self) -> None:
        self.calls = 0
        self.child_calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest_observation = runtime_context.get("latest_agent_loop_observation") or {}
        if latest_observation:
            self.latest_observations.append(latest_observation)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if runtime_context.get("subagent_worker"):
            self.child_calls += 1
            if latest_observation:
                assert latest_observation["status"] == "failed"
                content = {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Repair child implementation after failed observation.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "repair delegated artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "verify repaired delegated artifact",
                        }
                    ],
                    "runtime_requests": [],
                    "agent_loop_decision": {
                        "next_action": {
                            "action": "tool",
                            "reason": "Repair with a corrected child tool action.",
                            "target_task_id": task_id,
                            "capability_ref": {"type": "tool", "name": "write_file"},
                            "expected_observation": {"summary": "Child repair succeeds."},
                            "risk": "medium",
                            "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                            "evidence_refs": [latest_observation["observation_id"]],
                        }
                    },
                    "completion_notes": "child repaired",
                }
            else:
                content = {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Make an initial child attempt that validation will reject.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return notes\n",
                                "overwrite": True,
                            },
                            "reason": "create incomplete delegated artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "capture child validation failure",
                        }
                    ],
                    "runtime_requests": [],
                    "agent_loop_decision": {
                        "next_action": {
                            "action": "tool",
                            "reason": "Try the delegated implementation.",
                            "target_task_id": task_id,
                            "capability_ref": {"type": "tool", "name": "write_file"},
                            "expected_observation": {
                                "summary": "Child validation may fail and require repair.",
                                "next_recommended_action": "repair",
                            },
                            "risk": "medium",
                            "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                            "evidence_refs": [],
                        }
                    },
                    "completion_notes": "child initial attempt",
                }
        elif latest_observation:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after repaired subagent worker observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "The subagent worker repaired and verified the task.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {
                            "summary": "Runtime records stop after repaired subagent completion."
                        },
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [latest_observation["observation_id"]],
                    }
                },
                "completion_notes": "parent loop stopped after child repair",
            }
        else:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Delegate this task to a multi-round subagent.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "subagent",
                        "reason": "Independent implementation can be repaired inside a child loop.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "subagent", "name": "subagent"},
                        "expected_observation": {
                            "summary": "Subagent worker completes after repair.",
                            "success_signal": "worker evidence is present",
                            "parallel_safety": "serial",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 2, "tool_budget_units": 6},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "subagent dispatch requested",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-subagent-multi-round-execute",
            raw_response={},
        )


class FakeSubagentReadonlyFanoutClient:
    def __init__(self) -> None:
        self.calls = 0
        self.child_calls = 0
        self.latest_observations: list[dict] = []
        self.child_task_ids: list[str] = []
        self._lock = Lock()

    def chat(self, request: ChatRequest) -> ChatResponse:
        with self._lock:
            self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest_observation = runtime_context.get("latest_agent_loop_observation") or {}
        if latest_observation:
            self.latest_observations.append(latest_observation)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if runtime_context.get("subagent_fanout_child"):
            with self._lock:
                self.child_calls += 1
                self.child_task_ids.append(task_id)
            tool_calls = [
                {
                    "tool_name": "run_command",
                    "args": {"command": 'python -c "assert True"'},
                }
            ]
            if request.worker_transport == "tool_use":
                return ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    usage=TokenUsage(5, 8, 13),
                    model_provider="fake",
                    model_name="fake-subagent-readonly-fanout",
                    raw_response=_tool_use_raw_response(tool_calls),
                )
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": f"Run readonly fanout check for {task_id}.",
                "tool_calls": [],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {"command": 'python -c "assert True"'},
                        "reason": "readonly fanout verification",
                    }
                ],
                "runtime_requests": [],
                "completion_notes": f"readonly fanout child {task_id} completed",
            }
        elif latest_observation:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after readonly fanout subagent observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "Readonly fanout workers completed.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {
                            "summary": "Runtime records stop after readonly fanout."
                        },
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [latest_observation["observation_id"]],
                    }
                },
                "completion_notes": "parent loop stopped",
            }
        else:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Delegate readonly fanout checks to subagents.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "schema_version": "0.1.0",
                    "decision_id": "agent-loop-decision-0001",
                    "run_id": "run-placeholder",
                    "task_id": task_id,
                    "created_at": "2026-05-29T10:00:00+08:00",
                    "next_action": {
                        "action": "subagent",
                        "reason": "Readonly checks can safely fan out.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "subagent", "name": "subagent"},
                        "expected_observation": {
                            "summary": "Readonly fanout workers complete.",
                            "success_signal": "all readonly workers pass",
                            "parallel_safety": "readonly",
                        },
                        "risk": "low",
                        "budget_hint": {"model_calls": 2, "tool_budget_units": 2},
                        "evidence_refs": [],
                    },
                },
                "completion_notes": "subagent readonly fanout requested",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(4, 6, 10),
            model_provider="fake",
            model_name="fake-subagent-readonly-fanout",
            raw_response={},
        )


class FakeExplodingExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise AssertionError("runtime-managed validation probe should not call model")


class FakeSubagentReadonlyFanoutWriteClient(FakeSubagentReadonlyFanoutClient):
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        if runtime_context.get("subagent_fanout_child"):
            with self._lock:
                self.calls += 1
                self.child_calls += 1
            task_id = str(request.metadata.get("task_id") or "task-0001")
            return ChatResponse(
                content=json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "task_id": task_id,
                        "summary": "Attempt an unsafe write from readonly fanout.",
                        "tool_calls": [
                            {
                                "tool_name": "write_file",
                                "args": {
                                    "path": "readonly_fanout_violation.txt",
                                    "content": "bad",
                                    "overwrite": True,
                                },
                                "reason": "unsafe write",
                            }
                        ],
                        "verification": [],
                        "runtime_requests": [],
                        "completion_notes": "should be denied",
                    },
                    ensure_ascii=False,
                ),
                finish_reason="stop",
                usage=TokenUsage(4, 6, 10),
                model_provider="fake",
                model_name="fake-subagent-readonly-fanout-write",
                raw_response={},
            )
        return super().chat(request)


class FakeBoundedLoopExecuteClient:
    def __init__(self) -> None:
        self.calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest_observation = runtime_context.get("latest_agent_loop_observation") or {}
        if latest_observation:
            self.latest_observations.append(latest_observation)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if self.calls == 1:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Create notes module and ask Runtime for a follow-up loop decision.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                        "reason": "create the requested module",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                        },
                        "reason": "verify the module behavior",
                    }
                ],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "A tool action should create and verify the module.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {
                            "summary": "Tool execution should succeed and then return to the loop.",
                            "success_signal": "verified notes module exists",
                            "requires_follow_up_decision": True,
                            "next_recommended_action": "stop",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "src/notes_tool.py contains a working add_note function",
            }
        else:
            assert latest_observation["observation_type"] == "tool_result"
            assert latest_observation["status"] == "succeeded"
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after reviewing successful tool observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "The latest observation proves the task is complete.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {"summary": "Runtime records a stop observation."},
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [latest_observation["observation_id"]],
                    }
                },
                "completion_notes": "bounded loop stopped after observation",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-bounded-loop-execute",
            raw_response={},
        )


class FakeRepairAfterFailureLoopClient:
    def __init__(self) -> None:
        self.calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest_observation = runtime_context.get("latest_agent_loop_observation") or {}
        if latest_observation:
            self.latest_observations.append(latest_observation)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if self.calls == 1:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Make a tool attempt that will fail validation.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return notes\n",
                            "overwrite": True,
                        },
                        "reason": "create an intentionally incomplete module",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": 'python -c "raise SystemExit(1)"',
                            "expected_returncodes": [0],
                        },
                        "reason": "force validation failure for loop recovery",
                    }
                ],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "Use a tool action so Runtime can observe failure.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {
                            "summary": "Validation failure should become repair observation.",
                            "next_recommended_action": "repair",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "validation should fail",
            }
        else:
            assert latest_observation["status"] == "failed"
            assert latest_observation["next_recommended_action"] == "repair"
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Route failed observation into repair.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "repair",
                        "reason": "The failed observation needs the debug repair path.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "repair"},
                        "expected_observation": {"summary": "Runtime records repair routing."},
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
                        "evidence_refs": [latest_observation["observation_id"]],
                    }
                },
                "completion_notes": "repair requested",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-repair-after-failure-loop",
            raw_response={},
        )


def _failing_tool_action(task_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "task_id": task_id,
        "summary": "Make a tool attempt that fails validation.",
        "tool_calls": [
            {
                "tool_name": "write_file",
                "args": {
                    "path": "src/notes_tool.py",
                    "content": "def add_note(notes, text):\n    return notes\n",
                    "overwrite": True,
                },
                "reason": "create an intentionally incomplete module",
            }
        ],
        "verification": [
            {
                "tool_name": "run_command",
                "args": {
                    "command": 'python -c "raise SystemExit(1)"',
                    "expected_returncodes": [0],
                },
                "reason": "force validation failure for loop recovery",
            }
        ],
        "agent_loop_decision": {
            "next_action": {
                "action": "tool",
                "reason": "Use a tool action so Runtime can observe failure.",
                "target_task_id": task_id,
                "capability_ref": {"type": "tool", "name": "write_file"},
                "expected_observation": {
                    "summary": "Validation failure should become a repair observation.",
                    "next_recommended_action": "repair",
                },
                "risk": "medium",
                "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                "evidence_refs": [],
            }
        },
        "completion_notes": "validation should fail",
    }


def _repair_action(task_id: str, observation_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "task_id": task_id,
        "summary": "Route the failed observation into repair.",
        "tool_calls": [],
        "verification": [],
        "runtime_requests": [],
        "agent_loop_decision": {
            "next_action": {
                "action": "repair",
                "reason": "The failed observation needs a repair retry.",
                "target_task_id": task_id,
                "capability_ref": {"type": "runtime", "name": "repair"},
                "expected_observation": {"summary": "Runtime records repair routing."},
                "risk": "medium",
                "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
                "evidence_refs": [observation_id] if observation_id else [],
            }
        },
        "completion_notes": "repair requested",
    }


class FakeAutoRepairThenSucceedClient:
    """tool(fail) -> repair -> tool(succeed) -> stop, driven by the latest observation."""

    def __init__(self) -> None:
        self.calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest = runtime_context.get("latest_agent_loop_observation") or {}
        if latest:
            self.latest_observations.append(latest)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        status = str(latest.get("status") or "")
        observation_type = str(latest.get("observation_type") or "")
        if not latest:
            content = _failing_tool_action(task_id)
        elif observation_type == "tool_result" and status == "failed":
            content = _repair_action(task_id, str(latest.get("observation_id") or ""))
        elif observation_type == "repair_result":
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Repair the module so verification passes.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                        "reason": "write the corrected module",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                        },
                        "reason": "verify the corrected module",
                    }
                ],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "Retry the tool now that the module is corrected.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {
                            "summary": "Tool execution should succeed and complete the task.",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "repair retry should pass",
            }
        else:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after reviewing the successful tool observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "The latest observation proves the task is complete.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {"summary": "Runtime records a stop observation."},
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [str(latest.get("observation_id") or "")],
                    }
                },
                "completion_notes": "bounded loop stopped after success",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-auto-repair-then-succeed",
            raw_response={},
        )


class FakeAlwaysFailRepairClient:
    """tool(fail) -> repair, forever: exercises the auto-repair termination fuses."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest = runtime_context.get("latest_agent_loop_observation") or {}
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if str(latest.get("observation_type") or "") == "tool_result" and (
            str(latest.get("status") or "") == "failed"
        ):
            content = _repair_action(task_id, str(latest.get("observation_id") or ""))
        else:
            content = _failing_tool_action(task_id)
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-always-fail-repair",
            raw_response={},
        )


def _replan_action(task_id: str, observation_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "task_id": task_id,
        "summary": "Route the failed observation into a task-level replan.",
        "tool_calls": [],
        "verification": [],
        "runtime_requests": [],
        "agent_loop_decision": {
            "next_action": {
                "action": "replan",
                "reason": "This task's approach is wrong; re-approach it within the same goal.",
                "target_task_id": task_id,
                "capability_ref": {"type": "runtime", "name": "replan"},
                "expected_observation": {"summary": "Runtime records replan routing."},
                "risk": "medium",
                "budget_hint": {"model_calls": 1, "tool_budget_units": 0},
                "evidence_refs": [observation_id] if observation_id else [],
            }
        },
        "completion_notes": "replan requested",
    }


class FakeAutoReplanThenSucceedClient:
    """tool(fail) -> replan -> tool(succeed) -> stop, driven by the latest observation."""

    def __init__(self) -> None:
        self.calls = 0
        self.latest_observations: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest = runtime_context.get("latest_agent_loop_observation") or {}
        if latest:
            self.latest_observations.append(latest)
        task_id = str(request.metadata.get("task_id") or "task-0001")
        status = str(latest.get("status") or "")
        observation_type = str(latest.get("observation_type") or "")
        if not latest:
            content = _failing_tool_action(task_id)
        elif observation_type == "tool_result" and status == "failed":
            content = _replan_action(task_id, str(latest.get("observation_id") or ""))
        elif observation_type == "replan_result":
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Re-approach the module so verification passes.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                        "reason": "write the corrected module after replanning",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                        },
                        "reason": "verify the re-approached module",
                    }
                ],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "Retry the tool now that the approach is corrected.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {
                            "summary": "Tool execution should succeed and complete the task.",
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 3},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "replan retry should pass",
            }
        else:
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Stop after reviewing the successful tool observation.",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "The latest observation proves the task is complete.",
                        "target_task_id": task_id,
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {"summary": "Runtime records a stop observation."},
                        "risk": "low",
                        "budget_hint": {"model_calls": 0, "tool_budget_units": 0},
                        "evidence_refs": [str(latest.get("observation_id") or "")],
                    }
                },
                "completion_notes": "bounded loop stopped after success",
            }
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-auto-replan-then-succeed",
            raw_response={},
        )


class FakeAlwaysFailReplanClient:
    """tool(fail) -> replan, forever: exercises the auto-replan termination fuses."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        runtime_context = payload.get("runtime_context") or {}
        latest = runtime_context.get("latest_agent_loop_observation") or {}
        task_id = str(request.metadata.get("task_id") or "task-0001")
        if str(latest.get("observation_type") or "") == "tool_result" and (
            str(latest.get("status") or "") == "failed"
        ):
            content = _replan_action(task_id, str(latest.get("observation_id") or ""))
        else:
            content = _failing_tool_action(task_id)
        return ChatResponse(
            content=json.dumps(content, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(5, 8, 13),
            model_provider="fake",
            model_name="fake-always-fail-replan",
            raw_response={},
        )


class FakeDisjointWriteExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        path = "out/alpha.txt" if task_id == "task-0001" else "out/beta.txt"
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": f"Write {path}.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": path,
                                "content": task_id,
                                "overwrite": True,
                            },
                            "reason": "write disjoint output",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    'python -c "from pathlib import Path; '
                                    f"assert Path('{path}').read_text() == '{task_id}'\""
                                )
                            },
                            "reason": "verify disjoint output",
                        }
                    ],
                    "completion_notes": f"{path} written",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-disjoint-write-execute",
            raw_response={},
        )


class FakeReadonlyWriteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-readonly")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Try to write from a readonly task.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "readonly_violation.txt",
                                "content": "should not be written",
                                "overwrite": True,
                            },
                            "reason": "should be denied by tool permission profile",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-readonly-write",
            raw_response={},
        )


class FakeOutOfScopeWriteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Try to write outside the declared write scope.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "blocked/output.txt",
                                "content": "out of scope",
                                "overwrite": True,
                            },
                            "reason": "should be denied by write_scope",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-out-of-scope-write",
            raw_response={},
        )


class FakeOutOfScopeReadClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Try to read outside the declared read scope.",
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "args": {"path": "blocked.txt"},
                            "reason": "should be denied by read_scope",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-out-of-scope-read",
            raw_response={},
        )


class FakeOutOfScopePatchClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Try to patch outside the declared write scope.",
                    "tool_calls": [
                        {
                            "tool_name": "apply_patch",
                            "args": {
                                "patch": ("--- a/blocked.py\n+++ b/blocked.py\n@@\n+VALUE = 1\n")
                            },
                            "reason": "should be denied by write_scope",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-out-of-scope-patch",
            raw_response={},
        )


class FakeScopeExpansionRequestClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Request write scope before making an out-of-scope change.",
                    "tool_calls": [],
                    "verification": [],
                    "runtime_requests": [
                        {
                            "request_type": "scope_expansion",
                            "risk": "medium",
                            "reason": "Need to write generated/report.md, which is outside current write_scope.",
                            "details": {"write_scope": ["generated/report.md"]},
                        }
                    ],
                    "completion_notes": "Waiting for runtime contract review.",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-scope-expansion-request",
            raw_response={},
        )


class FakeGeneratedReportClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str(request.metadata.get("task_id") or "task-0001")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Write the report after scope expansion.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "generated/report.md",
                                "content": "# Report\n",
                                "overwrite": True,
                            },
                            "reason": "write approved report artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"from pathlib import Path; assert Path('generated/report.md').read_text() == '# Report\\n'\""
                            },
                            "reason": "verify report content",
                        }
                    ],
                    "completion_notes": "generated/report.md contains the report.",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(3, 4, 7),
            model_provider="fake",
            model_name="fake-generated-report",
            raw_response={},
        )


class RecordingContextExecuteClient:
    def __init__(self) -> None:
        self.runtime_contexts: list[dict] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        self.runtime_contexts.append(payload["runtime_context"])
        task_id = request.metadata["task_id"]
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Create notes module and verify Python can import it.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "verify the module behavior",
                        }
                    ],
                    "completion_notes": "src/notes_tool.py contains a working add_note function",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-context-execute",
            raw_response={},
        )


class FakeDisallowedToolClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Try to use a disallowed tool.",
                    "tool_calls": [
                        {
                            "tool_name": "unknown_tool",
                            "args": {},
                            "reason": "should be rejected before registry execution",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "not completed",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-disallowed",
            raw_response={},
        )


class FakeFailingVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create a module but fail verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "VALUE = 1\n",
                                "overwrite": True,
                            },
                            "reason": "create a file",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": 'python -c "raise SystemExit(1)"'},
                            "reason": "simulate failed verification",
                        }
                    ],
                    "completion_notes": "verification should fail",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-failing",
            raw_response={},
        )


class FakeBadDocVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Write a markdown note but provide a brittle verification command.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "docs/validation_batch_note.md",
                                "content": "# Validation Batch\n\n- Verify document-only tasks.\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested documentation artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    'python -c "from pathlib import Path; '
                                    'paths=["docs/validation_batch_note.md"]; print(paths)"'
                                )
                            },
                            "reason": "this malformed command should be replaced",
                        }
                    ],
                    "completion_notes": "docs/validation_batch_note.md contains the validation batch note",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-bad-doc-verification",
            raw_response={},
        )


class FakeNoopImplementationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Claim implementation is complete without changing files.",
                    "tool_calls": [],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": 'python -c "assert True"'},
                            "reason": "noop verification",
                        }
                    ],
                    "completion_notes": "claimed complete",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-noop",
            raw_response={},
        )


class FakeNoVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Write the module but skip verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "claimed complete",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-no-verification",
            raw_response={},
        )


class FakeInlineVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Write the module and put verification in tool_calls.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        },
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                            },
                            "reason": "verify the module behavior",
                        },
                    ],
                    "verification": [],
                    "completion_notes": "verified from inline tool_calls",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-inline-verification",
            raw_response={},
        )


class FakeReservedToolArgsClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Write the module with extra reserved tool args.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                                "context": "model should not pass this",
                                "agent_id": "wrong",
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\"",
                                "context": "reserved",
                                "task_id": "reserved",
                            },
                            "reason": "verify the module behavior",
                        }
                    ],
                    "completion_notes": "reserved args should be ignored",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-reserved-tool-args",
            raw_response={},
        )


class FakeModelSurfaceExecuteClient:
    def __init__(self) -> None:
        self.available_tools: list[str] = []
        self.model_surface: dict = {}

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        self.available_tools = payload["available_tools"]
        self.model_surface = payload["model_tool_surface"]
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Use model-facing search and test primitives.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "produce the expected artifact before inspection",
                        },
                        {
                            "tool_name": "grep",
                            "args": {"pattern": "def add_note", "path": "src"},
                            "reason": "inspect implementation with the model-facing search primitive",
                        },
                    ],
                    "verification": [
                        {
                            "tool_name": "run_tests",
                            "args": {"command": 'python -c "assert True"'},
                            "reason": "verify through the model-facing test primitive",
                        }
                    ],
                    "completion_notes": "model-facing tool surface was consumed",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model-surface",
            raw_response={},
        )


class FakeUnsafeVerificationClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Write the module with unsafe shell verification.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                            "reason": "create the requested module",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "echo unsafe > ../../out.txt",
                                "expected_returncodes": [0],
                            },
                            "reason": "unsafe shell command should be replaced",
                        }
                    ],
                    "completion_notes": "unsafe verification should be replaced",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-unsafe-verification",
            raw_response={},
        )


class FakeInvalidThenValidExecuteClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content="not json",
                finish_reason="stop",
                usage=TokenUsage(1, 1, 2),
                model_provider="fake",
                model_name="fake-invalid",
                raw_response={},
            )
        return FakeExecuteClient().chat(request)


class FakeInvalidExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="not json",
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-invalid",
            raw_response={},
        )


class FakeProviderNetworkFailureClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError(
            "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred>"
        )








def _enable_auto_repair(tmp_path: Path, *, max_repair_attempts_per_task: int) -> None:
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["auto_repair"] = True
    policy.setdefault("budgets", {})["max_repair_attempts_per_task"] = max_repair_attempts_per_task
    # The active budget profile wins over top-level budgets (resolve_budget_limits), so
    # override the effective per-task repair cap there too.
    profile = str(policy.get("active_budget_profile") or "")
    profiles = policy.get("budget_profiles")
    if profile and isinstance(profiles, dict) and isinstance(profiles.get(profile), dict):
        profiles[profile]["max_repair_attempts_per_task"] = max_repair_attempts_per_task
    policy_path.write_text(json.dumps(policy), encoding="utf-8")




def test_validation_probe_plan_uses_deterministic_goal_spec_fallback(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()

    plan = PlanCommand(
        tmp_path,
        "run capability selection validation probe",
        model_client=ExplodingPlanClient(),
        validation_probe_ids=["capability_selection_path"],
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    goal_spec = json.loads((run_dir / "goal_spec.json").read_text(encoding="utf-8"))
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    task = task_plan["tasks"][0]
    assert goal_spec["goal_id"] == "goal-validation-probe"
    assert goal_spec["goal_type"] == "report"
    assert task["task_kind"] == "diagnostic"
    assert task["runtime_profile_hints"]["validation_probe_ids"] == [
        "capability_selection_path"
    ]
    assert any(item["type"] == "goal_spec_fallback" for item in events)


def test_execute_command_blocks_high_risk_low_quality_delegation_before_model(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0]["risk_score"] = 0.95
    task_plan["tasks"][0]["allowed_tools"] = ["write_file"]
    task_plan["tasks"][0]["write_scope"] = []
    task_plan["tasks"][0]["expected_artifacts"] = ["src/"]
    task_plan["tasks"][0]["expected_changed_files"] = []
    task_plan_path.write_text(json.dumps(task_plan), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ExplodingExecuteClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    workers = [
        json.loads(line)
        for line in (run_dir / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert workers[-1]["status"] == "denied"
    assert workers[-1]["brief_quality"]["status"] == "warn"
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[-1]["failure_type"] == "delegation_brief_quality_gate"






def test_execute_command_attributes_provider_network_failure_before_tools(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeProviderNetworkFailureClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    failures = [
        json.loads(line)
        for line in (run_dir / "task_failures.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert failures[-1]["failure_type"] == "provider_network"
    assert "provider route evidence" in "\n".join(failures[-1]["recommendations"])
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failure_event = next(
        event for event in progress if event["title"] == "Task action failed before tools"
    )
    assert failure_event["data"]["failure_type"] == "provider_network"
    assert not (run_dir / "tool_calls.jsonl").exists()






























def test_execute_command_blocks_implementation_task_without_changed_artifacts(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeNoopImplementationClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "required changed artifact was not produced" in task_plan["tasks"][0]["notes"]


















def test_execute_command_pauses_direct_execute_when_task_plan_quality_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-07T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.5,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.25,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.50; 2 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                }
            ],
            "recommendations": ["Add expected_artifacts before execution."],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["task_plan_quality_gate_blocks"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()

    assert result.completed == 0
    assert result.blocked == 0
    assert result.executed_tasks[0].status == "paused"
    assert result.executed_tasks[0].evidence_path is not None
    assert not (tmp_path / "src" / "notes_tool.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "paused"
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "task_plan_quality_gate"


def _notes_verify_call(path: str = "src/notes_tool.py") -> dict:
    """A run_command the 立真身 correctness gate (RA7b-4) counts as verification evidence: a real
    implementation task must verify, so the model-driven fakes run a command that confirms the
    produced artifact exists (cwd = workspace root). Keeps the fakes honest about the contract."""
    return {
        "tool_name": "run_command",
        "args": {"command": f"python -c \"import os; assert os.path.exists('{path}')\""},
    }


class FakeModelDrivenClient:
    """立真身 JSON transport client: returns ``{narration, tool_calls, done}`` per the
    model-driven turn contract (NOT the FSM's agent_loop_decision.next_action table).

    Step 1: write the expected artifact through the real gateway (done=false).
    Step 2: model stops calling tools (done=true) — the loop's single control branch = completed.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.transports: list[str] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        self.transports.append(str(request.worker_transport))
        if self.calls == 1:
            payload = {
                "narration": "创建并验证 notes 工具模块。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": (
                                "python -c "
                                '"from src.notes_tool import add_note; '
                                'assert add_note([], \'x\') == [\'x\']"'
                            )
                        },
                    },
                ],
                "done": False,
            }
        else:
            payload = {"narration": "已创建并确认 notes 工具。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model-driven",
            raw_response={},
        )


def test_execute_command_model_driven_turn_flag_routes_through_real_thing(
    tmp_path: Path,
) -> None:
    """立真身灰度接入：flag 开 → 整任务走模型驱动单循环（model→tool→observation→model），
    经真 gateway 产出工件、模型 narration 上主线程、run summary 如实记 completed。"""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeModelDrivenClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert result.blocked == 0
    # 每轮都走 JSON transport（立真身通路），不是 FSM 的 next_action 填表。
    assert client.transports and all(transport == "json" for transport in client.transports)
    # 真的经 gateway 产出了工件。
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith(
        "def add_note"
    )
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # 模型自己的声音（narration）上了主线程。
    assert any(
        event.get("transcript_kind") == "assistant_message"
        and event.get("channel") == "model"
        and event.get("display_level") == "main"
        and (event.get("data") or {}).get("model_driven_turn")
        for event in user_progress
    )
    # 收口没被 schema-double-trap 静默降级。
    loop_summary = json.loads(
        (run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8")
    )
    assert loop_summary["status"] == "completed"
    assert loop_summary["exit_reason"] == "completed"


class FakeModelDrivenRecoveryClient:
    """立真身: first tool call fails through the REAL gateway (write_file without overwrite on an
    existing file → file_exists), the model reads the failure observation and retries with
    overwrite=True, then stops. Guards two things: (1) a non-ok observation is recorded with a
    VALID user_progress status (not "warning") so it never crashes the loop; (2) the model
    self-recovers from a real failure with no FSM repair branch."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "写入 notes 模块。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                        },
                    }
                ],
                "done": False,
            }
        elif self.calls == 2:
            payload = {
                "narration": "文件已存在，改用 overwrite 重写并验证。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    _notes_verify_call(),
                ],
                "done": False,
            }
        else:
            payload = {"narration": "notes 模块已就绪。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model-driven-recovery",
            raw_response={},
        )


class FakeModelDrivenMultiFileClient:
    """立真身 across a multi-file task: writes two files in one step, verifies, then stops.
    Proves the model-driven loop produces multiple artifacts through the real gateway."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "创建 notes 模块与它的测试。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/test_notes_tool.py",
                            "content": "from notes_tool import add_note\n\n\ndef test_add():\n    assert add_note([], 'x') == ['x']\n",
                            "overwrite": True,
                        },
                    },
                    _notes_verify_call(),
                ],
                "done": False,
            }
        else:
            payload = {"narration": "两个文件都已创建。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model-driven-multifile",
            raw_response={},
        )


def test_execute_command_model_driven_turn_multi_file(tmp_path: Path) -> None:
    """立真身 produces multiple files in one task (multi-artifact coverage)."""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenMultiFileClient()
    ).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith(
        "def add_note"
    )
    assert (tmp_path / "src" / "test_notes_tool.py").read_text(encoding="utf-8").startswith(
        "from notes_tool"
    )


def test_execute_command_model_driven_turn_failed_observation_does_not_crash(
    tmp_path: Path,
) -> None:
    """A non-ok tool observation must be recorded with a valid status and fed back — the model
    self-recovers and the task completes (regression: status="warning" crashed the loop)."""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    # Seed an existing file so the first (no-overwrite) write_file fails through the real gateway.
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes_tool.py").write_text("# placeholder\n", encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeModelDrivenRecoveryClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert client.calls == 3  # fail → recover → done
    # The failed observation was recorded (a valid-status progress event), and recovery overwrote.
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith(
        "def add_note"
    )


class FakeModelDrivenSkillClient:
    """立真身 reaches for a methodology skill (skill__debug) to load its procedure on demand, then
    proceeds — proves the optional methodology layer is reachable through the real gateway."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "先加载 debug 方法论。",
                "tool_calls": [{"tool_name": "skill__debug", "args": {}}],
                "done": False,
            }
        elif self.calls == 2:
            payload = {
                "narration": "创建并验证 notes 模块。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    _notes_verify_call(),
                ],
                "done": False,
            }
        else:
            payload = {"narration": "完成。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-skill",
            raw_response={},
        )


def test_execute_command_model_driven_turn_invokes_methodology_skill(tmp_path: Path) -> None:
    """立真身 can invoke a bundled methodology skill on demand (progressive disclosure): the call
    routes through the gateway's skill adapter, loads the procedure, and the task still completes."""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenSkillClient()
    ).run()

    assert result.completed == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    skill_invocations = [
        json.loads(line)
        for line in (run_dir / "skill_invocations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(inv.get("skill_name") == "debug" for inv in skill_invocations)


class FakeModelDrivenPrematureStopClient:
    """立真身 tries to finish before producing the expected artifact; the stop-guardrail hook holds
    the loop open until it exists, then the model writes it and completes."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {"narration": "看起来不用做什么。", "tool_calls": [], "done": True}
        elif self.calls == 2:
            payload = {
                "narration": "好的,我来创建并验证 notes 模块。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    _notes_verify_call(),
                ],
                "done": False,
            }
        else:
            payload = {"narration": "已创建。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-premature",
            raw_response={},
        )


def test_stop_guardrail_forces_continue_when_artifact_missing(tmp_path: Path) -> None:
    """Isolated: the stop-guardrail holds the loop open when an expected file is absent."""
    record = {
        "hook_name": "pre_final",
        "data": {"root": str(tmp_path), "expected_artifacts": ["result.py"]},
    }
    decision = _methodology_stop_guardrail_decision(record)
    assert decision is not None
    assert decision.continue_turn is True
    assert "result.py" in decision.additional_context


def test_stop_guardrail_allows_stop_when_artifact_exists(tmp_path: Path) -> None:
    (tmp_path / "result.py").write_text("x\n", encoding="utf-8")
    record = {
        "hook_name": "pre_final",
        "data": {"root": str(tmp_path), "expected_artifacts": ["result.py"]},
    }
    assert _methodology_stop_guardrail_decision(record) is None


def test_stop_guardrail_ignores_prose_placeholder(tmp_path: Path) -> None:
    # A task's write_scope/expected_artifacts may hold prose (e.g. "implementation artifact");
    # the guardrail must NOT treat it as a file to check (else it would loop forever).
    record = {
        "hook_name": "pre_final",
        "data": {"root": str(tmp_path), "expected_artifacts": ["implementation artifact"]},
    }
    assert _methodology_stop_guardrail_decision(record) is None


def test_turn_start_reminder_skips_strong_tier() -> None:
    record = {
        "hook_name": "turn_start",
        "data": {"iteration": 1, "model_tier": "strong", "methodology_skill_names": ["skill__debug"]},
    }
    assert _methodology_turn_start_decision(record) is None


def test_turn_start_reminder_fires_weak_tier_kickoff_only() -> None:
    weak = {
        "hook_name": "turn_start",
        "data": {"iteration": 1, "model_tier": "medium", "methodology_skill_names": ["skill__debug"]},
    }
    decision = _methodology_turn_start_decision(weak)
    assert decision is not None
    assert "methodology reminder" in decision.additional_context
    assert "skill__debug" in decision.additional_context
    # Not on later turns (kickoff only — do not bloat every turn).
    later = {**weak, "data": {**weak["data"], "iteration": 3}}
    assert _methodology_turn_start_decision(later) is None


def test_execute_command_model_driven_turn_premature_stop_continues_and_fires_hooks(
    tmp_path: Path,
) -> None:
    """The model-driven loop holds open past a premature stop and completes, and the control hooks
    actually FIRE (policy allows the new hook points) — recorded in runtime_hooks.jsonl."""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeModelDrivenPrematureStopClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith(
        "def add_note"
    )
    # Control hooks are no longer blocked by policy — the pre_final point fired and was recorded.
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    hook_events = [
        json.loads(line)
        for line in (run_dir / "runtime_hooks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("hook_name") == "pre_final" for event in hook_events)


class FakeModelDrivenDelegatingClient:
    """Lead 立真身 delegates a sub-task to a coder expert via spawn_subagent; the child runs its own
    bounded loop (distinguished by the '-sub-' task id) and produces the artifact, then the lead
    finishes. One fake model plays both roles, branching on the request's task_id."""

    def __init__(self) -> None:
        self.parent_calls = 0
        self.child_calls = 0
        self.spawned = False

    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str((request.metadata or {}).get("task_id") or "")
        if "-sub-" in task_id:
            self.child_calls += 1
            if self.child_calls == 1:
                payload = {
                    "narration": "创建 notes 模块。",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "src/notes_tool.py",
                                "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                                "overwrite": True,
                            },
                        }
                    ],
                    "done": False,
                }
            else:
                payload = {"narration": "子任务完成。", "tool_calls": [], "done": True}
        else:
            self.parent_calls += 1
            if self.parent_calls == 1:
                self.spawned = True
                payload = {
                    "narration": "把实现委派给 coder 专家，随后验证产物。",
                    "tool_calls": [
                        {
                            "tool_name": "spawn_subagent",
                            "args": {
                                "role": "coder",
                                "task": "create the notes module",
                                "write_scope": ["src/notes_tool.py"],
                            },
                        },
                        _notes_verify_call(),
                    ],
                    "done": False,
                }
            else:
                payload = {"narration": "专家已完成,任务结束。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-delegating",
            raw_response={},
        )


def test_execute_command_model_driven_turn_spawn_subagent(tmp_path: Path) -> None:
    """The lead model delegates to a coder expert via spawn_subagent; the child runs its own 立真身
    loop and produces the artifact, and only a summary rides back to the lead (MoE via tool call)."""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["model_driven_turn"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeModelDrivenDelegatingClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert client.spawned is True  # lead delegated
    assert client.child_calls >= 2  # the child ran its OWN loop
    # The child expert produced the artifact through the real gateway.
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith(
        "def add_note"
    )

    # Part B4 frontend pull-up: delegation is VISIBLE on the lead's main thread as two
    # subagent_summary events (dispatch + returned summary), which light up the wired "子 agent"
    # narrative card (ADR-0022 ③). The expert's OWN narration stays in the Inspector, not masquerading
    # as the lead's voice.
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    subagent_main = [
        e
        for e in events
        if e.get("transcript_kind") == "subagent_summary" and e.get("display_level") == "main"
    ]
    phases = {(e.get("data") or {}).get("subagent_phase") for e in subagent_main}
    assert phases == {"dispatch", "result"}
    assert all((e.get("data") or {}).get("subagent_role") == "coder" for e in subagent_main)
    # Same delegation → shared child_task_id (frontend groups dispatch+result into one card).
    assert len({(e.get("data") or {}).get("child_task_id") for e in subagent_main}) == 1
    # The child expert's narration is Inspector evidence, tagged with its role — never a main-thread
    # "模型叙述" masquerading as the lead.
    child_narration = [
        e
        for e in events
        if e.get("transcript_kind") == "assistant_message"
        and (e.get("data") or {}).get("subagent_role") == "coder"
    ]
    assert child_narration
    assert all(e.get("display_level") == "inspector" for e in child_narration)


class FakeConcurrentReviewersClient:
    """Lead delegates to TWO read-only reviewer experts in ONE tool batch. Each child blocks on a
    shared Barrier(2) on its first turn: if the fan-out is concurrent both children reach the barrier
    together and pass; if it were serial the first child's wait would time out (BrokenBarrier). The
    barrier passing IS the deterministic concurrency proof (ADR-0023 B1-a)."""

    def __init__(self) -> None:
        self.parent_calls = 0
        self._barrier = Barrier(2, timeout=8)
        self._lock = Lock()
        self._seen_children: set[str] = set()
        self.child_task_ids: set[str] = set()
        self.barrier_ok = False

    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str((request.metadata or {}).get("task_id") or "")
        if "-sub-" in task_id:
            first = False
            with self._lock:
                if task_id not in self._seen_children:
                    self._seen_children.add(task_id)
                    self.child_task_ids.add(task_id)
                    first = True
            if first:
                try:
                    self._barrier.wait()
                    self.barrier_ok = True
                except BrokenBarrierError:
                    pass
                payload = {
                    "narration": f"审阅 {task_id}。",
                    "tool_calls": [{"tool_name": "read_file", "args": {"path": "notes/subject.md"}}],
                    "done": False,
                }
            else:
                payload = {"narration": "审阅完成。", "tool_calls": [], "done": True}
        else:
            self.parent_calls += 1
            if self.parent_calls == 1:
                payload = {
                    "narration": "并发委派两位 reviewer 专家审阅。",
                    "tool_calls": [
                        {"tool_name": "spawn_subagent", "args": {"role": "reviewer", "task": "review section A"}},
                        {"tool_name": "spawn_subagent", "args": {"role": "reviewer", "task": "review section B"}},
                    ],
                    "done": False,
                }
            else:
                payload = {"narration": "两位 reviewer 已完成审阅。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-concurrent-reviewers",
            raw_response={},
        )


def test_execute_command_concurrent_readonly_subagent_fanout(tmp_path: Path) -> None:
    """ADR-0023 B1-a: with agent_loop.concurrent_subagents on, a batch of ≥2 spawn_subagent calls to
    read-only experts runs concurrently on a ThreadPool. Proven deterministically by a Barrier(2) the
    two reviewers must reach together; also asserts both delegations surface on the main thread."""
    InitCommand(tmp_path).run()
    (tmp_path / "notes").mkdir(exist_ok=True)
    (tmp_path / "notes" / "subject.md").write_text("# Subject under review\n", encoding="utf-8")
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    agent_loop = policy.setdefault("agent_loop", {})
    agent_loop["model_driven_turn"] = True
    agent_loop["concurrent_subagents"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "review the subject notes", model_client=FakePlanClient()).run()
    client = FakeConcurrentReviewersClient()

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    # Concurrency proof: both reviewers reached the shared barrier at the same time.
    assert client.barrier_ok is True
    assert len(client.child_task_ids) == 2
    # Both delegations are visible on the lead's main thread (dispatch + result per expert).
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    result_cards = [
        e
        for e in events
        if e.get("transcript_kind") == "subagent_summary"
        and e.get("display_level") == "main"
        and (e.get("data") or {}).get("subagent_phase") == "result"
    ]
    assert len(result_cards) == 2
    assert all((e.get("data") or {}).get("subagent_role") == "reviewer" for e in result_cards)
    # Concurrent children minted DISTINCT child_task_ids (counter lock) and event_ids (per-path
    # sequence) — no collisions.
    assert len({(e.get("data") or {}).get("child_task_id") for e in result_cards}) == 2
    assert len({e.get("event_id") for e in events}) == len(events)
    # B4: the read-only fan-out stamps its own batch identity too, so the UI can say "2 experts in
    # parallel" without inferring it from card order.
    assert all((e.get("data") or {}).get("concurrent") is True for e in result_cards)
    assert all(
        (e.get("data") or {}).get("batch_mode") == "readonly_fanout" for e in result_cards
    )
    assert len({(e.get("data") or {}).get("batch_id") for e in result_cards}) == 1
    assert all((e.get("data") or {}).get("read_only") is True for e in result_cards)


class FakeConcurrentWritersClient:
    """Lead delegates to TWO coder experts in ONE tool batch (ADR-0023 B1-b). With a barrier each
    child blocks on its first turn so both must run concurrently (proof); each writes into its OWN
    candidate workspace, then the merge gate reconciles. ``conflict`` makes both declare + write the
    SAME path (merge gate must block, nothing promoted); otherwise they write disjoint files (both
    promote into the shared workspace). ``use_barrier=False`` drops the barrier so a SERIAL fallback
    (isolated-write flag off) does not hang. One fake plays lead + both children."""

    def __init__(self, *, conflict: bool = False, use_barrier: bool = True) -> None:
        self.conflict = conflict
        self.use_barrier = use_barrier
        self.parent_calls = 0
        self._barrier = Barrier(2, timeout=8) if use_barrier else None
        self._lock = Lock()
        self._seen: set[str] = set()
        self.child_task_ids: set[str] = set()
        self.barrier_ok = False

    def _child_file(self, task_id: str) -> str:
        if self.conflict:
            return "src/shared.py"
        # Children are prepared in spawn-arg order → -sub-01 = alpha, -sub-02 = beta (deterministic).
        return "src/alpha.py" if task_id.endswith("-01") else "src/beta.py"

    def _scopes(self) -> tuple[list[str], list[str]]:
        if self.conflict:
            return ["src/shared.py"], ["src/shared.py"]
        return ["src/alpha.py"], ["src/beta.py"]

    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = str((request.metadata or {}).get("task_id") or "")
        if "-sub-" in task_id:
            first = False
            with self._lock:
                if task_id not in self._seen:
                    self._seen.add(task_id)
                    self.child_task_ids.add(task_id)
                    first = True
            if first:
                if self._barrier is not None:
                    try:
                        self._barrier.wait()
                        self.barrier_ok = True
                    except BrokenBarrierError:
                        pass
                path = self._child_file(task_id)
                payload = {
                    "narration": f"写入 {path}。",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": path,
                                "content": f"# {path}\nvalue = 1\n",
                                "overwrite": True,
                            },
                        }
                    ],
                    "done": False,
                }
            else:
                payload = {"narration": "子任务完成。", "tool_calls": [], "done": True}
        else:
            self.parent_calls += 1
            if self.parent_calls == 1:
                scope_a, scope_b = self._scopes()
                tool_calls = [
                    {
                        "tool_name": "spawn_subagent",
                        "args": {"role": "coder", "task": "write module A", "write_scope": scope_a},
                    },
                    {
                        "tool_name": "spawn_subagent",
                        "args": {"role": "coder", "task": "write module B", "write_scope": scope_b},
                    },
                ]
                if not self.conflict:
                    # Disjoint writers promote before this verify runs (same batch, after the fan-out),
                    # so the command confirms both landed in the SHARED workspace.
                    tool_calls.append(
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c \"import os; assert os.path.exists('src/alpha.py') "
                                    "and os.path.exists('src/beta.py')\""
                                )
                            },
                        }
                    )
                payload = {
                    "narration": "并发委派两位 coder 专家写模块。",
                    "tool_calls": tool_calls,
                    "done": False,
                }
            else:
                payload = {"narration": "收尾。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-concurrent-writers",
            raw_response={},
        )


def _enable_isolated_writes(tmp_path: Path, *, isolated: bool) -> None:
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    agent_loop = policy.setdefault("agent_loop", {})
    agent_loop["model_driven_turn"] = True
    agent_loop["concurrent_subagents"] = True
    agent_loop["isolated_parallel_write_production_path"] = isolated
    policy_path.write_text(json.dumps(policy), encoding="utf-8")


def test_concurrent_write_flags_bind_to_permission_mode(tmp_path: Path) -> None:
    # User-authorized global-default flip (2026-07-14·ADR-0023): the concurrent-expert-fan-out flags
    # (B1-a readonly `concurrent_subagents` + B1-b isolated writes `isolated_parallel_write_
    # production_path`) default ON under auto/reviewed_auto so the model's concurrent expert cluster
    # is the default capability, and OFF under ask_everything (explicit step-by-step). This mirrors
    # the other autonomy rings; explicit agent_loop flags still override either way.
    cmd = ExecuteCommand(tmp_path)
    for mode in ("auto", "reviewed_auto", "balanced"):
        assert cmd._concurrent_subagents_enabled({"permission_mode": mode}) is True
        assert cmd._isolated_parallel_writes_enabled({"permission_mode": mode}) is True
    for mode in ("ask_everything", "ask"):
        assert cmd._concurrent_subagents_enabled({"permission_mode": mode}) is False
        assert cmd._isolated_parallel_writes_enabled({"permission_mode": mode}) is False
    # Missing/unknown mode → treated as the run default (reviewed_auto) → on.
    assert cmd._concurrent_subagents_enabled({}) is True
    assert cmd._isolated_parallel_writes_enabled({}) is True
    # Explicit flags still override the mode default (byte-reversible opt-out / opt-in).
    off = {
        "permission_mode": "auto",
        "agent_loop": {
            "concurrent_subagents": False,
            "isolated_parallel_write_production_path": False,
        },
    }
    assert cmd._concurrent_subagents_enabled(off) is False
    assert cmd._isolated_parallel_writes_enabled(off) is False
    on = {
        "permission_mode": "ask_everything",
        "agent_loop": {
            "concurrent_subagents": True,
            "isolated_parallel_write_production_path": True,
        },
    }
    assert cmd._concurrent_subagents_enabled(on) is True
    assert cmd._isolated_parallel_writes_enabled(on) is True


def test_autopilot_mode_is_not_marked_stricter_than_balanced_on_the_tool_surface(
    tmp_path: Path,
) -> None:
    """The most autonomous tier must not be the most restricted one.

    `auto` was missing from the shell-allowed set, so it was the only mode whose tool surface marked
    `shell` and `run_tests` "deny" — stricter than `reviewed_auto`, which is backwards. This pins the
    ordering. It is NOT a live behaviour fix: today the surface's `permission` field gates nothing
    (the model payload carries tool names only; enforcement is in ToolExecutionGateway), so both
    tiers really do offer shell either way. The point is that the inversion cannot come back and
    start biting if that field is ever honoured.
    """
    cmd = ExecuteCommand(tmp_path)
    assert cmd._shell_allowed({"permission_mode": "auto"}) is True
    assert cmd._shell_allowed({"permission_mode": "reviewed_auto"}) is True
    assert cmd._shell_allowed({"permission_mode": "ask_everything"}) is False

    surface = model_tool_surface(["run_command"], allow_shell=cmd._shell_allowed({"permission_mode": "auto"}))
    offered = {tool["name"]: tool["permission"] for tool in surface}
    assert offered["shell"] != "deny"
    assert offered["run_tests"] != "deny"


def test_execute_command_concurrent_isolated_writes_disjoint_promote(tmp_path: Path) -> None:
    """ADR-0023 B1-b: with isolated_parallel_write_production_path on, a batch of ≥2 writing experts
    runs CONCURRENTLY, each in its own candidate workspace; the merge gate sees disjoint writes and
    promotes both into the shared workspace. Concurrency proven by a Barrier(2); isolation+promotion
    proven by both files landing and a merge-gate-ok card."""
    InitCommand(tmp_path).run()
    _enable_isolated_writes(tmp_path, isolated=True)
    plan = PlanCommand(tmp_path, "create alpha and beta modules", model_client=FakePlanClient()).run()
    client = FakeConcurrentWritersClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    # Concurrency proof: both writers reached the shared barrier together.
    assert client.barrier_ok is True
    assert len(client.child_task_ids) == 2
    # Both disjoint writers were promoted from their isolated candidates into the SHARED workspace.
    assert (tmp_path / "src" / "alpha.py").exists()
    assert (tmp_path / "src" / "beta.py").exists()
    assert result.completed == 1

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    # Isolation actually happened: candidate workspaces were created and a merge-gate dry-run ran.
    assert (run_dir / "merge_gate_dry_runs.jsonl").exists()
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    merge_cards = [
        e for e in events if (e.get("data") or {}).get("subagent_phase") == "merge_gate"
    ]
    assert merge_cards and all((e.get("data") or {}).get("ok") is True for e in merge_cards)
    # Distinct child_task_ids + globally unique event_ids under concurrency (counter lock / per-path
    # sequence).
    assert len(client.child_task_ids) == 2
    assert len({e.get("event_id") for e in events}) == len(events)


def test_execute_command_concurrent_isolated_writes_conflict_blocked(tmp_path: Path) -> None:
    """ADR-0023 B1-b safety: two writers claiming the SAME path are blocked by the merge gate — the
    isolated changes stay in their candidates and the SHARED workspace is never corrupted with a
    partial/racing merge. The lead sees the failure (cognition stays with the model, ADR-0016)."""
    InitCommand(tmp_path).run()
    _enable_isolated_writes(tmp_path, isolated=True)
    plan = PlanCommand(tmp_path, "create the shared module", model_client=FakePlanClient()).run()
    client = FakeConcurrentWritersClient(conflict=True)

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    # They still ran concurrently (both reached the barrier) — the block is at reconcile, not run.
    assert client.barrier_ok is True
    assert len(client.child_task_ids) == 2
    # Merge gate blocked → nothing promoted; the shared workspace is untouched.
    assert not (tmp_path / "src" / "shared.py").exists()
    assert result.completed == 0

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    merge_cards = [
        e for e in events if (e.get("data") or {}).get("subagent_phase") == "merge_gate"
    ]
    assert merge_cards and all((e.get("data") or {}).get("ok") is False for e in merge_cards)


def test_execute_command_isolated_writes_flag_off_stays_serial(tmp_path: Path) -> None:
    """Reversibility: with the isolated-write flag OFF (default), a 2-writer batch runs SERIALLY on the
    shared workspace — no candidate isolation, no merge gate — byte-identical to today. Both files land
    via direct writes and no merge-gate card is emitted."""
    InitCommand(tmp_path).run()
    _enable_isolated_writes(tmp_path, isolated=False)
    plan = PlanCommand(tmp_path, "create alpha and beta modules", model_client=FakePlanClient()).run()
    client = FakeConcurrentWritersClient(use_barrier=False)

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert (tmp_path / "src" / "alpha.py").exists()
    assert (tmp_path / "src" / "beta.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    # Serial path → no candidate isolation → no merge-gate reconciliation.
    assert not (run_dir / "merge_gate_dry_runs.jsonl").exists()
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert not any((e.get("data") or {}).get("subagent_phase") == "merge_gate" for e in events)


def _subagent_cards(tmp_path: Path, run_id: str, phase: str) -> list[dict]:
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [e for e in events if (e.get("data") or {}).get("subagent_phase") == phase]


def test_concurrent_batch_stamps_batch_identity_on_cards(tmp_path: Path) -> None:
    """B4: concurrency is IN the evidence, not inferred. Before this, the only way to know two experts
    ran in parallel was to guess from card ordering (concurrent_experts_smoke inferred it from
    [dispatch, dispatch, ...]). Every card a batch fans out now carries batch_id/batch_size/concurrent,
    so the UI reads the fact off a field. The merge-gate card binds back to the batch it reconciled."""
    InitCommand(tmp_path).run()
    _enable_isolated_writes(tmp_path, isolated=True)
    plan = PlanCommand(tmp_path, "create alpha and beta modules", model_client=FakePlanClient()).run()

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeConcurrentWritersClient()).run()

    dispatch = _subagent_cards(tmp_path, plan.run_id, "dispatch")
    results = _subagent_cards(tmp_path, plan.run_id, "result")
    assert len(dispatch) == 2 and len(results) == 2
    for card in dispatch + results:
        data = card["data"]
        assert data["concurrent"] is True
        assert data["batch_size"] == 2
        assert data["batch_mode"] == "isolated_writes"
    # One batch, one id — both experts belong to the SAME fan-out, and each has its own slot.
    batch_ids = {c["data"]["batch_id"] for c in dispatch + results}
    assert len(batch_ids) == 1
    assert {c["data"]["batch_index"] for c in dispatch} == {0, 1}
    # The merge gate binds back to the batch it reconciled.
    merge = _subagent_cards(tmp_path, plan.run_id, "merge_gate")
    assert merge and merge[0]["data"]["batch_id"] == batch_ids.pop()
    # Result cards now carry what the expert actually DID (was returned to the lead model only).
    changed = sorted(f for c in results for f in c["data"]["changed_files"])
    assert changed == ["src/alpha.py", "src/beta.py"]
    assert all(c["data"]["read_only"] is False for c in results)
    assert all(c["data"]["backend"] for c in results)


def test_serial_spawn_carries_no_batch_identity(tmp_path: Path) -> None:
    """B4 reversibility: a SERIAL spawn is not a batch, so its cards stay byte-identical — no batch_id,
    and crucially no ``concurrent`` flag that would let the UI claim parallelism that never happened."""
    InitCommand(tmp_path).run()
    _enable_isolated_writes(tmp_path, isolated=False)
    plan = PlanCommand(tmp_path, "create alpha and beta modules", model_client=FakePlanClient()).run()

    ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeConcurrentWritersClient(use_barrier=False)
    ).run()

    cards = _subagent_cards(tmp_path, plan.run_id, "dispatch") + _subagent_cards(
        tmp_path, plan.run_id, "result"
    )
    assert cards
    for card in cards:
        assert "batch_id" not in card["data"]
        assert "concurrent" not in card["data"]


@pytest.mark.spine_default
def test_execute_command_default_routes_through_model_driven_spine(tmp_path: Path) -> None:
    """RA7 翻默认锁定：策略里**不设** model_driven_turn 键时，走的就是立真身脊梁（生产默认）。

    这个用例 `@spine_default` 显式退出 conftest 的 RA7 legacy-FSM pin，因此它验证的是**真实翻转
    后的默认**——没有任何对启用判定的打桩。默认路径必须产出工件、把 model_driven_turn 标记写进
    user_progress，并如实收口为 completed。"""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeModelDrivenClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    assert result.completed == 1
    assert result.blocked == 0
    # 默认（无 flag）就走 JSON transport 的立真身通路，而不是 FSM 的 next_action 填表。
    assert client.transports and all(transport == "json" for transport in client.transports)
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith("def add_note")
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any((event.get("data") or {}).get("model_driven_turn") for event in user_progress)




# --- RA7b-4 立真身正确性 gate（确定性证据边界，ADR-0016）--------------------------------------
# 模型吐 done 只是它的认知；工件改没改、验证跑没跑 / 过没过由 harness 用与 FSM 同一套 task_contract
# 复核。契约不满足即 blocked——把 FSM 的确定性 done-gate（验证失败 / 缺验证 / 无改动工件 / 越权写）
# 原样搬进脊梁，语义不减配（区别：脊梁直写工作区，blocked 时产物仍在盘上，不做候选丢弃）。


class FakeModelDrivenVerifyFailsClient:
    """立真身写出工件，但验证命令非零退出（真 gateway 跑）。完成契约据此判 blocked。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "写出 notes 模块并验证。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    },
                    {
                        "tool_name": "run_command",
                        "args": {"command": 'python -c "import sys; sys.exit(1)"'},
                    },
                ],
                "done": False,
            }
        else:
            payload = {"narration": "自认为完成。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-verify-fails",
            raw_response={},
        )


class FakeModelDrivenNoVerifyClient:
    """立真身写出工件却完全不验证——required-verification 契约缺失，判 blocked。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "写出 notes 模块就收工。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                    }
                ],
                "done": False,
            }
        else:
            payload = {"narration": "自认为完成。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-no-verify",
            raw_response={},
        )


class FakeModelDrivenOutOfScopeClient:
    """立真身把写落在 write_scope 之外——真 gateway 拒绝，无改动工件，契约判 blocked。验证通过以
    隔离出"缺改动工件"这一条违约（证明越权写在脊梁上照样被证据边界拦住）。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "narration": "尝试写到 blocked/ 并验证。",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "blocked/output.txt",
                            "content": "nope\n",
                            "overwrite": True,
                        },
                    },
                    {"tool_name": "run_command", "args": {"command": 'python -c "assert True"'}},
                ],
                "done": False,
            }
        else:
            payload = {"narration": "自认为完成。", "tool_calls": [], "done": True}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-mdt-out-of-scope",
            raw_response={},
        )


@pytest.mark.spine_default
def test_model_driven_spine_blocks_when_verification_fails(tmp_path: Path) -> None:
    """正确性 gate：验证命令失败 → 任务 blocked（模型说 done 也否决），note 记"验证未通过"，
    verification_calls 如实计数。脊梁直写：与 FSM 候选丢弃不同，产物仍留在工作区。"""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenVerifyFailsClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert result.executed_tasks[0].verification_calls == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "verification did not pass" in task_plan["tasks"][0]["notes"]
    # 直写模型：blocked 时产物仍在盘上（不做候选隔离/丢弃）。
    assert (tmp_path / "src" / "notes_tool.py").exists()


@pytest.mark.spine_default
def test_model_driven_spine_blocks_required_task_without_verification(tmp_path: Path) -> None:
    """正确性 gate：实现任务写了工件却零验证 → blocked，note 记"缺必需验证"。"""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenNoVerifyClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert result.executed_tasks[0].verification_calls == 0
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "required verification was not provided" in task_plan["tasks"][0]["notes"]


@pytest.mark.spine_default
def test_model_driven_spine_blocks_out_of_scope_write_without_artifact(tmp_path: Path) -> None:
    """正确性 gate + 权限边界：写落在 write_scope 之外被真 gateway 拒 → 无改动工件 → blocked，
    文件没落盘，note 记"缺必需改动工件"。证明越权写在脊梁上照样被拦。"""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["write_file", "run_command"],
            "expected_artifacts": ["implementation artifact"],
            "write_scope": ["allowed/"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenOutOfScopeClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "blocked" / "output.txt").exists()
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "required changed artifact was not produced" in task_plan["tasks"][0]["notes"]


@pytest.mark.spine_default
def test_model_driven_spine_reports_verification_calls_on_success(tmp_path: Path) -> None:
    """happy path：写 + 验证通过 → completed，且 verification_calls 真实上报（不再硬编码 0）。"""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenClient()
    ).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert result.executed_tasks[0].verification_calls >= 1


class FakeModelDrivenVerifiesNeverDoneClient:
    """Writes the artifact + a passing verification, then NEVER emits done — so the loop runs until
    the round fuse trips (``budget_exhausted``) while the completion contract is already satisfied."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        verify = {
            "tool_name": "run_command",
            "args": {
                "command": (
                    "python -c "
                    '"from src.notes_tool import add_note; '
                    "assert add_note([], 'x') == ['x']\""
                )
            },
        }
        if self.calls == 1:
            tool_calls = [
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "src/notes_tool.py",
                        "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                        "overwrite": True,
                    },
                },
                verify,
            ]
        else:
            tool_calls = [verify]
        payload = {"narration": "持续验证但不收尾。", "tool_calls": tool_calls, "done": False}
        return ChatResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-never-done",
            raw_response={},
        )


@pytest.mark.spine_default
def test_model_driven_spine_completes_verified_work_even_when_round_fuse_trips(
    tmp_path: Path,
) -> None:
    """收敛正确性（真栈 ring_val_b 发现）：任务在撞上迭代保险丝（budget_exhausted）的同一轮已满足
    完成契约（工件 + 验证通过）→ 判 done，而非被保险丝盖成 blocked。否则已完成的活会被喂给
    goal-replan 环空转（0001→0002→0003…）。主流亦如此：模型把活干完就是 done，扁平计数只是防跑飞
    的兜底，绝不用来丢弃已验证完成的工作。"""
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    # max_iterations = max_rounds_per_task + 4 = 5 → the never-done fake exhausts the fuse quickly.
    policy.setdefault("agent_loop", {})["max_rounds_per_task"] = 1
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    client = FakeModelDrivenVerifiesNeverDoneClient()
    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=client).run()

    # The fake never says done, so the loop can only have ended by hitting the fuse — proving the
    # budget_exhausted branch was the one that finalized the (contract-satisfied) task.
    assert client.calls >= 2
    assert result.completed == 1
    assert result.blocked == 0
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "done"
