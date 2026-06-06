import json
from pathlib import Path
from threading import Lock

import pytest

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.promotions_command import PromotionsCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.commands.run_command import RunCommand
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
            content = {
                "schema_version": "0.1.0",
                "task_id": task_id,
                "summary": "Child subagent creates notes module and verifies it.",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "path": "src/notes_tool.py",
                            "content": "def add_note(notes, text):\n    return [*notes, text]\n",
                            "overwrite": True,
                        },
                        "reason": "create delegated artifact",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -c \"import sys; sys.path.insert(0, 'src'); from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
                        },
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
                                "command": "echo unsafe > out.txt",
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


def test_execute_command_runs_ready_task_and_updates_logs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8") == (
        "def add_note(notes, text):\n    return [*notes, text]\n"
    )

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    execute_envelope = json.loads(
        (run_dir / "prompt_envelope_execute.json").read_text(encoding="utf-8")
    )
    assert execute_envelope["mode"] == "execute"
    assert "capability_manifest" in execute_envelope["section_order"]
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "done"
    assert "working add_note" in task_plan["tasks"][0]["notes"]

    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "task_started" in events
    assert "task_completed" in events
    tool_calls = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert "write_file" in tool_calls
    assert "run_command" in tool_calls
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[0]["decision"] == "keep"
    assert experiments[0]["candidate"]["backup_ids"]
    assert experiments[0]["candidate"]["workspace"]
    assert experiments[0]["candidate"]["strategy"] in {"git_worktree", "temp_workspace"}
    assert experiments[0]["candidate"]["workspace_policy"] in {"worktree", "isolated_copy"}
    assert experiments[0]["candidate"]["backend_reason"]
    assert experiments[0]["candidate"]["promoted_files"] == ["src/notes_tool.py"]

    promotions = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [item["status"] for item in promotions] == ["auto_approved", "promoted"]
    assert promotions[-1]["promoted_files"] == ["src/notes_tool.py"]
    assert experiments[0]["metrics_after"]["verification_pass_rate"] == 1.0
    artifacts = [
        json.loads(line)
        for line in (run_dir / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert artifacts[0]["path"] == "src/notes_tool.py"
    assert artifacts[0]["type"] == "source_file"
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[0]["status"] == "done"
    assert evidence[0]["task"]["acceptance"]
    assert evidence[0]["candidate"]["promoted_files"] == ["src/notes_tool.py"]
    assert evidence[0]["candidate"]["strategy"] in {"git_worktree", "temp_workspace"}
    assert evidence[0]["candidate"]["backend_reason"]
    assert evidence[0]["contract_check"]["merge_gate"]["ok"] is True
    assert evidence[0]["contract_check"]["merge_gate"]["promotable_files"] == ["src/notes_tool.py"]
    assert evidence[0]["verification_results"][0]["ok"] is True
    validation_results = [
        json.loads(line)
        for line in (run_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["validation_result_id"] for item in validation_results] == [
        "validation-0001",
        "validation-0002",
    ]
    assert [item["status"] for item in validation_results] == ["passed", "passed"]
    assert validation_results[0]["command"] == "python -m py_compile src/notes_tool.py"
    assert "notes_tool import add_note" in validation_results[1]["command"]
    workers = [
        json.loads(line)
        for line in (run_dir / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert workers[0]["task_id"] == "task-0001"
    assert workers[0]["status"] == "succeeded"
    assert workers[0]["runtime_profile_id"].startswith("runtime-profile-")
    runtime_profiles = [
        json.loads(line)
        for line in (run_dir / "runtime_profiles.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert runtime_profiles[0]["runtime_profile_id"] == workers[0]["runtime_profile_id"]
    assert runtime_profiles[0]["model_profile_id"].startswith("model-profile-")
    assert runtime_profiles[0]["tool_permission_profile_id"].startswith("tools-profile-")
    assert (run_dir / "model_profiles.jsonl").exists()
    assert (run_dir / "tool_permission_profiles.jsonl").exists()
    assert (run_dir / "sandbox_profiles.jsonl").exists()
    assert (run_dir / "context_mounts.jsonl").exists()
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert worker_results[0]["worker_invocation_id"] == workers[0]["worker_invocation_id"]
    assert worker_results[0]["status"] == "succeeded"
    assert worker_results[0]["artifact_refs"] == ["artifact-0001"]
    assert worker_results[0]["validation_refs"] == ["validation-0001", "validation-0002"]
    assert worker_results[0]["cost"]["model_calls"] == 1
    assert worker_results[0]["cost"]["tool_calls"] == 3
    model_calls = [
        json.loads(line)
        for line in (run_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    execute_model_call = model_calls[-1]
    assert execute_model_call["runtime_profile_id"] == workers[0]["runtime_profile_id"]
    assert execute_model_call["model_profile_id"] == runtime_profiles[0]["model_profile_id"]
    assert execute_model_call["prompt_envelope_hash"] == execute_envelope["content_hash"]
    assert execute_model_call["prompt_envelope_path"].endswith("prompt_envelope_execute.json")
    assert execute_model_call["capability_manifest_hash"].startswith("sha256:")

    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 2
    assert cost_report["tool_calls"] == 3
    assert cost_report["estimated_input_tokens"] == 25
    assert cost_report["estimated_output_tokens"] == 45
    loop_observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert loop_observations[-1]["observation_type"] == "tool_result"
    assert loop_observations[-1]["status"] == "succeeded"
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))
    assert loop_summary["exit_reason"] == "completed"
    assert loop_summary["rounds_completed"] == 1


def test_execute_command_records_subagent_dispatch_gray_path(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeSubagentExecuteClient()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    executions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    workers = [
        json.loads(line)
        for line in (run_dir / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    runtime_profiles = [
        json.loads(line)
        for line in (run_dir / "runtime_profiles.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    context_budget_snapshots = [
        json.loads(line)
        for line in (run_dir / "context_budget_snapshots.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    child_plans = [
        json.loads(line)
        for line in (run_dir / "subagent_child_plans.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.completed == 1
    assert result.blocked == 0
    subagent_execution = next(item for item in executions if item["action"] == "subagent")
    assert subagent_execution["target"] == "subagent_dispatcher"
    worker = next(
        item
        for item in reversed(workers)
        if item["worker_invocation_id"] == subagent_execution["worker_invocation_id"]
    )
    worker_result = next(
        item
        for item in reversed(worker_results)
        if item["worker_result_id"] == subagent_execution["worker_result_id"]
    )
    assert worker["status"] == "succeeded"
    assert worker["worker_kind"] == "subagent"
    assert worker["parallel_safety"] == "serial"
    assert worker["parent_worker_invocation_id"] == "worker-0001"
    assert worker["child_plan_refs"] == ["subagent-child-plan-0001"]
    assert worker_result["status"] == "succeeded"
    assert worker_result["worker_kind"] == "subagent"
    assert worker_result["parent_worker_invocation_id"] == "worker-0001"
    assert worker_result["child_plan_refs"] == ["subagent-child-plan-0001"]
    assert child_plans[-1]["worker_invocation_id"] == subagent_execution["worker_invocation_id"]
    assert child_plans[-1]["parent_decision_id"] == subagent_execution["decision_id"]
    assert child_plans[-1]["child_tasks"][0]["parallel_safety"] == "serial"
    assert child_plans[-1]["scheduling_strategy"] == "serial_single_worker"
    subagent_profile = next(
        item
        for item in runtime_profiles
        if item["runtime_profile_id"] == worker["runtime_profile_id"]
    )
    assert subagent_profile["worker_kind"] == "subagent"
    assert subagent_profile["parallel_safety"] == "serial"
    assert subagent_profile["parent_runtime_profile_id"].startswith("runtime-profile-")
    subagent_budget = [
        item for item in context_budget_snapshots if item["scope"] == "subagent_child"
    ][-1]
    assert subagent_budget["worker_kind"] == "subagent"
    assert subagent_budget["isolation_policy"] == "subagent_child_context"
    assert (
        subagent_budget["parent_worker_invocation_id"] == subagent_execution["worker_invocation_id"]
    )
    assert subagent_budget["runtime_profile_id"] == subagent_profile["runtime_profile_id"]
    assert subagent_budget["estimated_tokens"] > 0
    assert subagent_budget["compact_boundary"]["status"] in {
        "not_required",
        "dedupe_recommended",
        "recommended",
        "required",
    }
    loop_observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    subagent_observation = next(
        item
        for item in loop_observations
        if item["source_execution_id"] == subagent_execution["execution_id"]
    )
    assert subagent_observation["observation_type"] == "subagent_result"
    assert subagent_observation["status"] == "succeeded"
    assert subagent_observation["next_recommended_action"] == "stop"
    assert "subagent-child-plan-0001" in subagent_observation["evidence_refs"]
    assert (
        client.latest_observations[-1]["observation_id"] == subagent_observation["observation_id"]
    )
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))
    assert loop_summary["exit_reason"] == "stop"
    assert loop_summary["recommended_command"] == "status --debug"


def test_execute_command_runs_subagent_child_bounded_loop_with_parent_evidence(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["subagent_max_rounds_per_task"] = 3
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeSubagentMultiRoundExecuteClient()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    assert result.completed == 1
    assert client.child_calls == 2
    assert (
        (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8").startswith("def add_note")
    )
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    tool_observations = [item for item in observations if item["observation_type"] == "tool_result"]
    assert [item["status"] for item in tool_observations[-2:]] == ["failed", "succeeded"]
    subagent_observation = [
        item for item in observations if item["observation_type"] == "subagent_result"
    ][-1]
    assert subagent_observation["status"] == "succeeded"
    assert (
        client.latest_observations[-1]["observation_id"] == subagent_observation["observation_id"]
    )
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    subagent_result = [item for item in worker_results if item.get("worker_kind") == "subagent"][-1]
    assert subagent_result["status"] == "succeeded"
    assert subagent_result["cost"]["model_calls"] == 2
    assert subagent_result["parent_worker_invocation_id"] == "worker-0001"
    assert subagent_result["child_plan_refs"] == ["subagent-child-plan-0001"]
    child_plans = [
        json.loads(line)
        for line in (run_dir / "subagent_child_plans.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert child_plans[-1]["worker_invocation_id"] == "worker-0002"
    assert child_plans[-1]["child_tasks"][0]["task_id"] == "task-0001"
    context_mounts = [
        json.loads(line)
        for line in (run_dir / "context_mounts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    subagent_mount = [
        item
        for item in context_mounts
        if item["includes"].get("isolation_policy") == "subagent_child_context"
    ][-1]
    assert subagent_mount["includes"]["parent_worker_invocation_id"] == "worker-0002"
    assert subagent_mount["includes"]["parallel_safety"] == "serial"
    context_budget_snapshots = [
        json.loads(line)
        for line in (run_dir / "context_budget_snapshots.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    subagent_budget = [
        item for item in context_budget_snapshots if item["scope"] == "subagent_child"
    ][-1]
    assert subagent_budget["parent_worker_invocation_id"] == "worker-0002"
    assert subagent_budget["sections"]["subagent_worker"] > 0
    assert subagent_budget["sections"]["parent_agent_loop_decision"] > 0
    assert subagent_budget["context_window_ratio"] >= 0
    candidate_manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (run_dir / "candidates").glob("*.json")
    ]
    subagent_candidates = [
        item for item in candidate_manifests if item.get("worker_kind") == "subagent"
    ]
    assert subagent_candidates
    assert all(item["parent_worker_invocation_id"] == "worker-0002" for item in subagent_candidates)
    task_evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        item["candidate"].get("worker_kind") == "subagent"
        and item["candidate"].get("parent_worker_invocation_id") == "worker-0002"
        for item in task_evidence
    )
    agent_graph = json.loads((run_dir / "agent_run_graph.json").read_text(encoding="utf-8"))
    subagent_plan = [
        item
        for item in agent_graph["child_worker_plans"]
        if item["worker_invocation_id"] == "worker-0002"
    ][-1]
    assert subagent_plan["parent_worker_invocation_id"] == "worker-0001"
    assert subagent_plan["subagent_child_plan_id"] == "subagent-child-plan-0001"
    assert subagent_plan["planned_child_count"] == 1
    assert subagent_plan["planned_child_tasks"][0]["task_id"] == "task-0001"


def test_execute_command_runs_subagent_readonly_fanout_child_workers(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["max_rounds_per_task"] = 2
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    plan = PlanCommand(tmp_path, "research two local checks", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "title": "Research local readonly checks",
            "description": "Inspect two local facts without writing files.",
            "acceptance": ["inspect alpha", "inspect beta"],
            "allowed_tools": ["list_files", "read_file", "search_text", "run_command"],
            "expected_artifacts": [],
            "expected_changed_files": [],
            "read_scope": [".asteria/project.json"],
            "write_scope": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": True,
                "allows_expected_failure": False,
            },
            "multi_agent_strategy": {
                "mode": "readonly_fanout",
                "max_child_workers": 2,
                "planner_child_plan": True,
                "coordination_policy": {
                    "write_allowed": False,
                    "requires_merge_gate": False,
                    "requires_summary": True,
                    "scale_out_limit": 2,
                },
            },
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")
    client = FakeSubagentReadonlyFanoutClient()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert client.child_calls == 2
    assert sorted(client.child_task_ids) == [
        "task-0001-child-worker-0002-01",
        "task-0001-child-worker-0002-02",
    ]
    child_plans = [
        json.loads(line)
        for line in (run_dir / "subagent_child_plans.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert child_plans[-1]["scheduling_strategy"] == "parallel_readonly_safe"
    assert len(child_plans[-1]["child_tasks"]) == 2
    workers = [
        json.loads(line)
        for line in (run_dir / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    readonly_workers = [
        item for item in workers if item.get("worker_kind") == "subagent_readonly_child"
    ]
    assert len(readonly_workers) == 2
    assert {item["status"] for item in readonly_workers} == {"succeeded"}
    assert {item["parent_worker_invocation_id"] for item in readonly_workers} == {"worker-0002"}
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    readonly_results = [
        item for item in worker_results if item.get("worker_kind") == "subagent_readonly_child"
    ]
    assert len(readonly_results) == 2
    assert {item["cost"]["model_calls"] for item in readonly_results} == {1}
    parent_subagent_result = [
        item for item in worker_results if item.get("worker_kind") == "subagent"
    ][-1]
    assert parent_subagent_result["status"] == "succeeded"
    assert parent_subagent_result["cost"]["model_calls"] == 2
    assert parent_subagent_result["child_plan_refs"] == ["subagent-child-plan-0001"]
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    subagent_observation = [
        item for item in observations if item["observation_type"] == "subagent_result"
    ][-1]
    assert subagent_observation["status"] == "succeeded"
    assert subagent_observation["next_recommended_action"] == "stop"
    agent_graph = json.loads((run_dir / "agent_run_graph.json").read_text(encoding="utf-8"))
    readonly_plans = [
        item
        for item in agent_graph["child_worker_plans"]
        if item["worker_invocation_id"]
        in {worker["worker_invocation_id"] for worker in readonly_workers}
    ]
    assert len(readonly_plans) == 2
    assert {item["parent_worker_invocation_id"] for item in readonly_plans} == {"worker-0002"}
    assert {item["collaboration_role"] for item in readonly_plans} == {"research_child"}


def test_execute_command_runtime_manages_readonly_validation_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research two local checks", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"] = [task_plan["tasks"][0]]
    task_plan["tasks"][0].update(
        {
            "title": "Runtime managed readonly probe",
            "description": "Inspect two local facts without writing files.",
            "acceptance": ["inspect alpha", "inspect beta"],
            "allowed_tools": ["list_files", "read_file", "search_text", "run_command"],
            "expected_artifacts": [],
            "expected_changed_files": [],
            "read_scope": [".asteria/project.json"],
            "write_scope": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "runtime_profile_hints": {
                "validation_probe_ids": ["readonly_fanout_succeeds"],
                "runtime_managed_validation_probe": True,
                "force_next_action": "subagent",
            },
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": True,
                "allows_expected_failure": False,
            },
            "multi_agent_strategy": {
                "mode": "readonly_fanout",
                "max_child_workers": 2,
                "planner_child_plan": True,
                "coordination_policy": {
                    "write_allowed": False,
                    "requires_merge_gate": False,
                    "requires_summary": True,
                    "scale_out_limit": 2,
                },
            },
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeExplodingExecuteClient(),
    ).run()

    assert result.completed == 1
    child_plans = [
        json.loads(line)
        for line in (run_dir / "subagent_child_plans.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert child_plans[-1]["scheduling_strategy"] == "parallel_readonly_safe"
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    readonly_results = [
        item for item in worker_results if item.get("worker_kind") == "subagent_readonly_child"
    ]
    assert len(readonly_results) == 2
    assert {item["status"] for item in readonly_results} == {"succeeded"}
    assert {item["cost"]["model_calls"] for item in readonly_results} == {0}


def test_execute_command_blocks_write_tool_in_subagent_readonly_fanout(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research two local checks", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "title": "Research local readonly checks",
            "description": "Inspect two local facts without writing files.",
            "acceptance": ["inspect alpha", "inspect beta"],
            "allowed_tools": ["list_files", "read_file", "search_text", "run_command"],
            "expected_artifacts": [],
            "expected_changed_files": [],
            "write_scope": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": True,
                "allows_expected_failure": False,
            },
            "multi_agent_strategy": {
                "mode": "readonly_fanout",
                "max_child_workers": 2,
                "planner_child_plan": True,
                "coordination_policy": {"write_allowed": False, "requires_merge_gate": False},
            },
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeSubagentReadonlyFanoutWriteClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "readonly_fanout_violation.txt").exists()
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    parent_subagent_result = [
        item for item in worker_results if item.get("worker_kind") == "subagent"
    ][-1]
    assert parent_subagent_result["status"] == "failed"
    assert "Readonly fanout child cannot use write tool" in parent_subagent_result["summary"]


def test_execute_command_runs_bounded_loop_after_tool_observation(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeBoundedLoopExecuteClient()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    executions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.completed == 1
    assert result.blocked == 0
    assert client.calls == 2
    assert client.latest_observations[0]["observation_type"] == "tool_result"
    assert [item["next_action"]["action"] for item in decisions[-2:]] == ["tool", "stop"]
    assert [item["action"] for item in executions[-2:]] == ["tool", "stop"]
    assert [item["observation_type"] for item in observations[-2:]] == [
        "tool_result",
        "stop_report",
    ]
    assert observations[-2]["next_recommended_action"] == "stop"
    assert observations[-1]["status"] == "stopped"
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))
    assert loop_summary["exit_reason"] == "stop"
    assert loop_summary["rounds_completed"] == 2


def test_execute_command_routes_failed_observation_to_repair_action(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    client = FakeRepairAfterFailureLoopClient()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=client,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.completed == 0
    assert result.blocked == 1
    assert client.calls == 2
    assert client.latest_observations[0]["status"] == "failed"
    assert [item["next_action"]["action"] for item in decisions[-2:]] == ["tool", "repair"]
    assert observations[-2]["observation_type"] == "tool_result"
    assert observations[-2]["status"] == "failed"
    assert observations[-2]["next_recommended_action"] == "repair"
    assert observations[-1]["observation_type"] == "repair_result"
    assert observations[-1]["status"] == "pending"
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))
    assert loop_summary["exit_reason"] == "repair_dispatch"
    assert loop_summary["recommended_command"] == "debug"


def test_execute_command_runtime_manages_repair_replan_validation_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "run repair validation probe",
        model_client=FakePlanClient(),
        validation_probe_ids=["repair_replan_path"],
    ).run()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ExplodingExecuteClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    executions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))

    assert result.completed == 0
    assert result.blocked == 1
    assert [item["next_action"]["action"] for item in decisions[-2:]] == ["tool", "repair"]
    assert [item["action"] for item in executions[-2:]] == ["tool", "repair"]
    assert observations[-2]["status"] == "failed"
    assert observations[-2]["next_recommended_action"] == "repair"
    assert observations[-1]["observation_type"] == "repair_result"
    assert observations[-1]["status"] == "pending"
    assert loop_summary["exit_reason"] == "repair_dispatch"
    assert loop_summary["recommended_command"] == "debug"


def test_execute_command_runtime_manages_ask_stop_validation_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "run ask stop validation probe",
        model_client=FakePlanClient(),
        validation_probe_ids=["ask_stop_path"],
    ).run()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ExplodingExecuteClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    executions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        json.loads(line)
        for line in (run_dir / "agent_loop_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))

    assert result.completed == 0
    assert result.blocked == 1
    assert decisions[-1]["next_action"]["action"] == "stop"
    assert executions[-1]["action"] == "stop"
    assert executions[-1]["target"] == "stop_report"
    assert observations[-1]["observation_type"] == "stop_report"
    assert observations[-1]["status"] == "stopped"
    assert loop_summary["exit_reason"] == "stop"
    assert loop_summary["recommended_command"] == "status --debug"


def test_execute_command_runtime_manages_context_pressure_validation_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "run context pressure validation probe",
        model_client=FakePlanClient(),
        validation_probe_ids=["context_pressure_path"],
    ).run()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ExplodingExecuteClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    snapshots = [
        json.loads(line)
        for line in (run_dir / "context_budget_snapshots.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    executions = [
        json.loads(line)
        for line in (run_dir / "agent_loop_execution_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))

    assert result.completed == 0
    assert result.blocked == 1
    assert snapshots[-1]["pressure_status"] == "hard_stop"
    assert snapshots[-1]["compact_boundary"]["status"] == "required"
    assert executions[-1]["action"] == "stop"
    assert executions[-1]["target"] == "stop_report"
    assert loop_summary["exit_reason"] == "stop"


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


def test_execute_command_runtime_manages_capability_selection_validation_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "run capability selection validation probe",
        model_client=FakePlanClient(),
        validation_probe_ids=["capability_selection_path"],
    ).run()

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=ExplodingExecuteClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "capability_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    invocations = [
        json.loads(line)
        for line in (run_dir / "mcp_invocations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    loop_summary = json.loads((run_dir / "agent_loop_run_summary.json").read_text(encoding="utf-8"))

    assert result.completed == 0
    assert result.blocked == 1
    assert decisions[-1]["capability_type"] == "mcp"
    assert decisions[-1]["decision"]["reason"]
    assert invocations[-1]["capability_decision"]["reason"]
    assert any(
        event.get("data", {}).get("capability_type") == "mcp"
        for event in progress
    )
    assert loop_summary["exit_reason"] == "stop"


def test_run_command_short_circuits_runtime_managed_capability_probe(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()

    result = RunCommand(
        tmp_path,
        goal="run capability selection validation probe",
        plan_model_client=FakePlanClient(),
        execute_model_client=ExplodingExecuteClient(),
        enable_research=False,
        max_iterations=1,
        validation_probe_ids=["capability_selection_path"],
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    step_names = [step.name for step in result.steps]
    loop_summary = json.loads((run_dir / "run_loop_summary.json").read_text(encoding="utf-8"))

    assert "validation-probe" in step_names
    assert "debug" not in step_names
    assert "review" not in step_names
    assert "compact" not in step_names
    assert (run_dir / "capability_decisions.jsonl").exists()
    assert (run_dir / "mcp_invocations.jsonl").exists()
    assert loop_summary["stop_reason"] == "runtime_managed_validation_probe_evidence_recorded"


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


def test_execute_command_records_run_loop_user_progress(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    titles = [event["title"] for event in progress]
    assert "Candidate workspace created" in titles
    assert "开始验证" in titles
    assert "Validation results recorded" in titles
    assert "Completion contract checked" in titles
    assert "Merge gate evaluated" in titles
    assert "Promotion started" in titles
    assert "Candidate promoted" in titles
    assert "Task execution evidence recorded" in titles
    assert any(event["channel"] == "file" and event["file_changes"] for event in progress)
    assert any(event["channel"] == "evidence" and event["phase"] == "result" for event in progress)


def test_execute_command_records_pre_tool_user_progress_when_action_fails(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeInvalidExecuteClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    titles = [event["title"] for event in progress]
    assert "Worker action requested" in titles
    assert "Task action failed before tools" in titles
    failure_event = next(
        event for event in progress if event["title"] == "Task action failed before tools"
    )
    assert failure_event["channel"] == "evidence"
    assert failure_event["phase"] == "blocked"
    assert failure_event["status"] == "blocked"
    assert failure_event["evidence_refs"]
    assert failure_event["data"]["failure_type"] == "exception"
    assert not (run_dir / "tool_calls.jsonl").exists()


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


def test_execute_command_records_runtime_request_user_progress(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["write_file"],
            "expected_artifacts": ["allowed/output.txt"],
            "expected_changed_files": ["allowed/output.txt"],
            "write_scope": ["allowed/output.txt"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeScopeExpansionRequestClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runtime_event = next(event for event in progress if event["title"] == "Runtime request created")
    assert runtime_event["channel"] == "progress"
    assert runtime_event["event_type"] == "decision"
    assert runtime_event["status"] == "waiting_user"
    assert runtime_event["evidence_refs"]
    assert not (run_dir / "tool_calls.jsonl").exists()


def test_execute_command_manual_promotion_keeps_candidate_isolated(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    policy_path = tmp_path / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["promotion"]["manual_approval_default"] = True
    policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "src" / "notes_tool.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    promotions = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert promotions[-1]["status"] == "pending_manual_approval"
    assert promotions[-1]["approval_mode"] == "manual"
    assert promotions[-1]["promotable_files"] == ["src/notes_tool.py"]
    assert Path(promotions[-1]["workspace"]).exists()

    approved = PromotionsCommand(
        root=tmp_path,
        action="approve",
        promotion_id=promotions[-1]["promotion_id"],
    ).run()

    assert approved.promotions[0]["status"] == "promoted"
    assert (tmp_path / "src" / "notes_tool.py").read_text(encoding="utf-8") == (
        "def add_note(notes, text):\n    return [*notes, text]\n"
    )


def test_execute_command_parallel_readonly_executes_readonly_batch(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research two local checks", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    base = {
        "schema_version": "0.1.0",
        "description": "Run a readonly verification command and record the outcome.",
        "status": "ready",
        "priority": "medium",
        "role": "CoderAgent",
        "depends_on": [],
        "acceptance": ["command exits successfully"],
        "allowed_tools": ["run_command"],
        "expected_artifacts": [],
        "task_kind": "research",
        "parallel_safety": "readonly",
        "completion_contract": {
            "requires_changed_artifact": False,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
        "created_at": "2026-05-13T10:00:00+08:00",
        "updated_at": "2026-05-13T10:00:00+08:00",
        "notes": "",
    }
    task_plan["tasks"] = [
        {**base, "task_id": "task-0001", "title": "Research alpha"},
        {**base, "task_id": "task-0002", "title": "Research beta"},
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        max_tasks=2,
        model_client=FakeReadonlyExecuteClient(),
        parallel_readonly=True,
    ).run()

    assert result.completed == 2
    assert result.blocked == 0
    assert [task.task_id for task in result.executed_tasks] == ["task-0001", "task-0002"]
    updated_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    assert [task["status"] for task in updated_plan["tasks"]] == ["done", "done"]
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "readonly_batch_selection" in events
    workers = [
        json.loads(line)
        for line in (run_dir / "workers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {worker["task_id"] for worker in workers} == {"task-0001", "task-0002"}
    assert len({worker["runtime_profile_id"] for worker in workers}) == 2
    runtime_profiles = [
        json.loads(line)
        for line in (run_dir / "runtime_profiles.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {profile["runtime_profile_id"] for profile in runtime_profiles} == {
        worker["runtime_profile_id"] for worker in workers
    }
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["status"] for item in worker_results] == ["succeeded", "succeeded"]
    agent_graph = json.loads((run_dir / "agent_run_graph.json").read_text(encoding="utf-8"))
    assert agent_graph["max_concurrency_observed"] == 2
    assert agent_graph["coordination_modes"] == ["readonly_batch_selection"]
    assert agent_graph["collaboration_summary"]["successful_workers"] == 2
    assert [plan["collaboration_role"] for plan in agent_graph["child_worker_plans"]] == [
        "research_child",
        "research_child",
    ]
    model_calls = [
        json.loads(line)
        for line in (run_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len({call["model_call_id"] for call in model_calls}) == len(model_calls)
    execute_profile_ids = {
        call["runtime_profile_id"] for call in model_calls if call["purpose"] == "task_execution"
    }
    assert execute_profile_ids == {worker["runtime_profile_id"] for worker in workers}
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 3


def test_execute_command_stabilizes_doc_only_verification(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path, "create a validation batch note", model_client=FakePlanClient()
    ).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "title": "Write validation batch note",
            "description": "Create docs/validation_batch_note.md with a short checklist.",
            "allowed_tools": ["write_file", "run_command"],
            "expected_artifacts": ["docs/validation_batch_note.md"],
            "expected_changed_files": ["docs/validation_batch_note.md"],
            "write_scope": ["docs/validation_batch_note.md"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "documentation",
            "parallel_safety": "serial",
            "completion_contract": {
                "requires_changed_artifact": True,
                "requires_verification": True,
                "allows_expected_failure": False,
            },
            "verification_policy": {"required": True, "commands": []},
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeBadDocVerificationClient(),
    ).run()

    assert result.completed == 1
    assert result.blocked == 0
    assert (
        (tmp_path / "docs" / "validation_batch_note.md")
        .read_text(encoding="utf-8")
        .startswith("# Validation Batch")
    )
    validation_results = [
        json.loads(line)
        for line in (run_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(validation_results) == 1
    assert "missing or empty" in validation_results[0]["command"]
    assert "docs/validation_batch_note.md" in validation_results[0]["command"]
    assert "bad" not in validation_results[0]["command"]


def test_execute_command_parallel_disjoint_writes_promotes_isolated_outputs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path, "write two independent outputs", model_client=FakePlanClient()
    ).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    base = {
        "schema_version": "0.1.0",
        "description": "Write an independent output file.",
        "status": "ready",
        "priority": "medium",
        "role": "CoderAgent",
        "depends_on": [],
        "acceptance": ["output file exists"],
        "allowed_tools": ["write_file", "run_command"],
        "expected_artifacts": [],
        "task_kind": "implementation",
        "parallel_safety": "disjoint_writes",
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
        "created_at": "2026-05-13T10:00:00+08:00",
        "updated_at": "2026-05-13T10:00:00+08:00",
        "notes": "",
    }
    task_plan["tasks"] = [
        {
            **base,
            "task_id": "task-0001",
            "title": "Write alpha",
            "expected_artifacts": ["out/alpha.txt"],
            "expected_changed_files": ["out/alpha.txt"],
            "read_scope": ["AGENTS.md"],
            "write_scope": ["out/alpha.txt"],
        },
        {
            **base,
            "task_id": "task-0002",
            "title": "Write beta",
            "expected_artifacts": ["out/beta.txt"],
            "expected_changed_files": ["out/beta.txt"],
            "read_scope": ["AGENTS.md"],
            "write_scope": ["out/beta.txt"],
        },
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        max_tasks=2,
        model_client=FakeDisjointWriteExecuteClient(),
        parallel_writes=True,
    ).run()

    assert result.completed == 2
    assert (tmp_path / "out" / "alpha.txt").read_text(encoding="utf-8") == "task-0001"
    assert (tmp_path / "out" / "beta.txt").read_text(encoding="utf-8") == "task-0002"
    updated_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    assert [task["status"] for task in updated_plan["tasks"]] == ["done", "done"]
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "parallel_safe_batch_selection" in events
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sorted(item["candidate"]["promoted_files"][0] for item in experiments) == [
        "out/alpha.txt",
        "out/beta.txt",
    ]
    worker_results = [
        json.loads(line)
        for line in (run_dir / "worker_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["status"] for item in worker_results] == ["succeeded", "succeeded"]
    agent_graph = json.loads((run_dir / "agent_run_graph.json").read_text(encoding="utf-8"))
    assert agent_graph["coordination_modes"] == ["parallel_safe_batch_selection"]
    assert agent_graph["collaboration_summary"]["total_workers"] == 2
    assert agent_graph["collaboration_summary"]["successful_workers"] == 2
    assert agent_graph["collaboration_summary"]["validation_refs"]
    assert all(plan["artifact_refs"] for plan in agent_graph["child_worker_plans"])
    assert [plan["collaboration_role"] for plan in agent_graph["child_worker_plans"]] == [
        "implementation_child",
        "implementation_child",
    ]


def test_execute_command_denies_write_tool_for_readonly_task(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research one local check", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"] = [
        {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Readonly research",
            "description": "Run a readonly research task.",
            "status": "ready",
            "priority": "medium",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": ["readonly task does not write files"],
            "allowed_tools": ["write_file"],
            "expected_artifacts": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": False,
                "allows_expected_failure": False,
            },
            "created_at": "2026-05-13T10:00:00+08:00",
            "updated_at": "2026-05-13T10:00:00+08:00",
            "notes": "",
        }
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeReadonlyWriteClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "readonly_violation.txt").exists()
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "ToolPermissionProfile denied write tool" in evidence[0]["summary"]


def test_execute_command_denies_write_file_outside_write_scope(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["write_file"],
            "expected_artifacts": ["allowed/output.txt"],
            "expected_changed_files": ["allowed/"],
            "write_scope": ["allowed/"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeOutOfScopeWriteClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "blocked" / "output.txt").exists()
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    runtime_requests = [
        json.loads(line)
        for line in (run_dir / "runtime_requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert runtime_requests[0]["request_type"] == "scope_expansion"
    assert runtime_requests[0]["details"]["write_scope"] == ["blocked/output.txt"]
    assert evidence[0]["failure_type"] == "runtime_request"


def test_execute_command_denies_read_file_outside_read_scope(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research one local check", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"] = [
        {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Readonly research",
            "description": "Read only from the declared scope.",
            "status": "ready",
            "priority": "medium",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": ["out of scope files are not read"],
            "allowed_tools": ["read_file"],
            "expected_artifacts": [],
            "read_scope": ["allowed.txt"],
            "write_scope": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": False,
                "allows_expected_failure": False,
            },
            "created_at": "2026-05-13T10:00:00+08:00",
            "updated_at": "2026-05-13T10:00:00+08:00",
            "notes": "",
        }
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeOutOfScopeReadClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    runtime_requests = [
        json.loads(line)
        for line in (run_dir / "runtime_requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert runtime_requests[0]["request_type"] == "context_request"
    assert runtime_requests[0]["details"]["read_scope"] == ["blocked.txt"]
    assert evidence[0]["failure_type"] == "runtime_request"


def test_execute_command_denies_apply_patch_outside_write_scope(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["apply_patch"],
            "expected_artifacts": ["allowed.py"],
            "expected_changed_files": ["allowed.py"],
            "write_scope": ["allowed.py"],
            "read_scope": ["AGENTS.md", "allowed.py"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeOutOfScopePatchClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "blocked.py").exists()
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    runtime_requests = [
        json.loads(line)
        for line in (run_dir / "runtime_requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert runtime_requests[0]["request_type"] == "scope_expansion"
    assert runtime_requests[0]["details"]["write_scope"] == ["blocked.py"]
    assert evidence[0]["failure_type"] == "runtime_request"


def test_execute_command_records_runtime_request_without_writing_outside_scope(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["write_file"],
            "expected_artifacts": ["allowed/output.txt"],
            "expected_changed_files": ["allowed/output.txt"],
            "write_scope": ["allowed/output.txt"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeScopeExpansionRequestClient(),
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "generated" / "report.md").exists()
    assert not (run_dir / "tool_calls.jsonl").exists()
    runtime_requests = [
        json.loads(line)
        for line in (run_dir / "runtime_requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert runtime_requests[0]["request_type"] == "scope_expansion"
    assert runtime_requests[0]["status"] == "decision_created"
    assert runtime_requests[0]["details"]["write_scope"] == ["generated/report.md"]
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "runtime_request"
    assert decisions[0]["metadata"]["runtime_request_ids"] == [
        runtime_requests[0]["runtime_request_id"]
    ]
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[0]["failure_type"] == "runtime_request"
    assert runtime_requests[0]["runtime_request_id"] in evidence[0]["summary"]


def test_resume_applies_runtime_request_and_allows_follow_up_write(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a generated report", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "allowed_tools": ["write_file", "run_command"],
            "expected_artifacts": ["generated/report.md"],
            "expected_changed_files": ["generated/report.md"],
            "write_scope": ["allowed/output.txt"],
            "read_scope": ["AGENTS.md"],
            "task_kind": "implementation",
            "parallel_safety": "serial",
        }
    )
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    requested = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeScopeExpansionRequestClient(),
    ).run()
    assert requested.blocked == 1
    runtime_request = json.loads(
        (run_dir / "runtime_requests.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )

    DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        decision_id="decision-0001",
        select_option_id="review_contract",
    ).run()
    resumed = ResumeCommand(
        tmp_path,
        run_id=plan.run_id,
        max_iterations=0,
        execute_model_client=FakeGeneratedReportClient(),
    ).run()
    assert resumed.applied_decisions == 1

    updated = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task = updated["tasks"][0]
    assert task["status"] == "ready"
    assert "generated/report.md" in task["write_scope"]
    assert "Runtime request approved via decision-0001" in task["notes"]
    assert "Recovered from Runtime OS evidence" in task["notes"]

    second_resume = ResumeCommand(
        tmp_path,
        run_id=plan.run_id,
        max_iterations=0,
        execute_model_client=FakeGeneratedReportClient(),
    ).run()
    assert second_resume.applied_decisions == 0
    updated_again = json.loads(task_plan_path.read_text(encoding="utf-8"))
    assert updated_again["tasks"][0]["write_scope"].count("generated/report.md") == 1

    executed = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeGeneratedReportClient(),
    ).run()
    assert executed.completed == 1
    assert (tmp_path / "generated" / "report.md").read_text(encoding="utf-8") == "# Report\n"
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    applied = [
        event
        for event in events
        if event["type"] == "decision_applied" and event["data"]["decision_id"] == "decision-0001"
    ]
    assert len(applied) == 1
    assert applied[0]["data"]["effect"] == "runtime_request_applied"
    resume_evidence = applied[0]["data"]["runtime_os_evidence"]
    assert resume_evidence["runtime_request_ids"] == [runtime_request["runtime_request_id"]]
    assert resume_evidence["latest_worker_result"]["status"] == "failed"
    assert resume_evidence["summary"]["blocked_execution_count"] == 1
    assert runtime_request["runtime_request_id"] in task["notes"]


def test_resume_applies_context_request_read_scope(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "research one local check", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"] = [
        {
            "schema_version": "0.1.0",
            "task_id": "task-0001",
            "title": "Read blocked file",
            "description": "Read only after context request approval.",
            "status": "ready",
            "priority": "medium",
            "role": "CoderAgent",
            "depends_on": [],
            "acceptance": ["request read scope"],
            "allowed_tools": ["read_file"],
            "expected_artifacts": [],
            "read_scope": ["allowed.txt"],
            "write_scope": [],
            "task_kind": "research",
            "parallel_safety": "readonly",
            "completion_contract": {
                "requires_changed_artifact": False,
                "requires_verification": False,
                "allows_expected_failure": False,
            },
            "created_at": "2026-05-13T10:00:00+08:00",
            "updated_at": "2026-05-13T10:00:00+08:00",
            "notes": "",
        }
    ]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    requested = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeOutOfScopeReadClient(),
    ).run()

    assert requested.blocked == 1
    decision = json.loads((run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    DecideCommand(
        tmp_path,
        run_id=plan.run_id,
        decision_id=decision["decision_id"],
        select_option_id="review_contract",
    ).run()

    resumed = ResumeCommand(
        tmp_path,
        run_id=plan.run_id,
        max_iterations=0,
        execute_model_client=FakeOutOfScopeReadClient(),
    ).run()

    assert resumed.applied_decisions == 1
    updated = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task = updated["tasks"][0]
    assert task["status"] == "ready"
    assert task["read_scope"].count("blocked.txt") == 1
    assert task["context_requirements"]["requested_paths"] == ["blocked.txt"]


def test_execute_command_injects_context_mount_and_task_contract(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    execute_client = RecordingContextExecuteClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=execute_client).run()

    assert result.completed == 1
    runtime_context = execute_client.runtime_contexts[0]
    assert runtime_context["context_mount"]["mount_type"] == "coding_context"
    assert runtime_context["context_mount"]["task_id"] == "task-0001"
    assert runtime_context["context_package"]["task_brief"]["task_id"] == "task-0001"
    assert (
        runtime_context["context_package"]["goal_brief"]["normalized_goal"]
        == "Create a tiny notes tool"
    )
    assert runtime_context["task_contract"]["read_scope"]
    assert runtime_context["task_contract"]["parallel_safety"] == "serial"


def test_execute_command_blocks_disallowed_tool_without_tool_call(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeDisallowedToolClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    assert "not allowed" in task_plan["tasks"][0]["notes"]
    assert not (run_dir / "tool_calls.jsonl").exists()


def test_execute_command_blocks_when_verification_fails(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeFailingVerificationClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    assert not (tmp_path / "src" / "notes_tool.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "blocked"
    tool_calls = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert "nonzero_exit" in tool_calls
    assert "restore_backup" not in tool_calls
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[0]["decision"] == "discard"
    assert experiments[0]["metrics_after"]["verification_pass_rate"] == 0.5
    assert experiments[0]["candidate"]["workspace"]
    assert (Path(experiments[0]["candidate"]["workspace"]) / "src" / "notes_tool.py").exists()
    assert experiments[0]["candidate"]["rollback"] == []
    assert experiments[0]["candidate"]["promoted_files"] == []
    assert not (run_dir / "artifacts.jsonl").exists()


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


def test_execute_command_blocks_required_task_without_verification(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeNoVerificationClient()
    ).run()

    assert result.completed == 0
    assert result.blocked == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert "required verification was not provided" in task_plan["tasks"][0]["notes"]
    assert not (tmp_path / "src" / "notes_tool.py").exists()
    experiments = [
        json.loads(line)
        for line in (run_dir / "experiments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert experiments[0]["contract_check"]["ok"] is False
    assert experiments[0]["contract_check"]["verification_total"] == 0
    task_failures = [
        json.loads(line)
        for line in (run_dir / "task_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert task_failures[0]["failure_type"] == "contract_violation"
    assert task_failures[0]["contract_check"]["verification_total"] == 0
    assert "Add a verification command" in task_failures[0]["recommendations"][0]
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[0]["status"] == "blocked"
    assert evidence[0]["failure_type"] == "contract_violation"
    assert evidence[0]["contract_check"]["verification_total"] == 0


def test_execute_command_uses_planned_verification_when_model_omits_it(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    command = (
        "python -c \"import sys; sys.path.insert(0, 'src'); "
        "from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
    )
    task_plan["tasks"][0]["validation_commands"] = [
        f"Execute `{command}` and assert exit code is 0."
    ]
    task_plan["tasks"][0]["verification_policy"] = {
        "required": True,
        "allow_expected_failure": False,
        "commands": task_plan["tasks"][0]["validation_commands"],
    }
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeNoVerificationClient()
    ).run()

    assert result.completed == 1
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[0]["contract_check"]["verification_total"] >= 1
    validations = [
        json.loads(line)
        for line in (run_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(command in item.get("command", "") for item in validations)


def test_execute_command_extracts_single_quoted_planned_verification(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    command = "python -m py_compile src/notes_tool.py"
    task_plan["tasks"][0]["validation_commands"] = [
        f"Execute '{command}' and assert exit code is 0."
    ]
    task_plan["tasks"][0]["verification_policy"] = {
        "required": True,
        "allow_expected_failure": False,
        "commands": task_plan["tasks"][0]["validation_commands"],
    }
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeNoVerificationClient()
    ).run()

    assert result.completed == 1
    validations = [
        json.loads(line)
        for line in (run_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(command in item.get("command", "") for item in validations)


def test_execute_command_treats_inline_run_command_as_verification(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeInlineVerificationClient()
    ).run()

    assert result.completed == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert evidence[0]["verification_results"][0]["ok"] is True
    assert evidence[0]["contract_check"]["verification_total"] == 2


def test_execute_command_filters_reserved_model_tool_args(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeReservedToolArgsClient()
    ).run()

    assert result.completed == 1
    tool_calls = (tmp_path / ".asteria" / "runs" / plan.run_id / "tool_calls.jsonl").read_text(
        encoding="utf-8"
    )
    assert "model should not pass this" not in tool_calls
    assert "reserved" not in tool_calls


def test_execute_command_exposes_model_tool_surface_and_records_mapping(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "notes_tool.py").write_text(
        "def add_note(notes, text):\n    return [*notes, text]\n",
        encoding="utf-8",
    )
    execute_client = FakeModelSurfaceExecuteClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=execute_client).run()

    assert result.completed == 1
    assert "grep" in execute_client.available_tools
    assert "run_tests" in execute_client.available_tools
    assert execute_client.model_surface["adapter"] == "model_to_runtime_registry"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    proposed = [event for event in progress if event.get("title") == "Worker action proposed"][-1]
    assert any(
        item["model_tool_name"] == "grep" and item["tool_name"] == "search_text"
        for item in proposed["data"]["model_tool_calls"]
    )
    assert any(
        event.get("data", {}).get("model_tool_name") == "grep"
        for event in progress
        if event.get("event_type") == "tool_call"
    )


def test_execute_command_replaces_unsafe_verification_commands(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    command = (
        "python -c \"import sys; sys.path.insert(0, 'src'); "
        "from notes_tool import add_note; assert add_note([], 'x') == ['x']\""
    )
    task_plan["tasks"][0]["validation_commands"] = [f"Execute `{command}`."]
    task_plan_path.write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

    result = ExecuteCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeUnsafeVerificationClient()
    ).run()

    assert result.completed == 1
    assert not (tmp_path / "out.txt").exists()
    assert not (run_dir / "decisions.jsonl").exists()
    evidence = [
        json.loads(line)
        for line in (run_dir / "task_execution_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(command in result["summary"] for result in evidence[0]["verification_results"])


def test_execute_command_retries_invalid_model_json_once(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    execute_client = FakeInvalidThenValidExecuteClient()

    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=execute_client).run()

    assert result.completed == 1
    assert execute_client.calls == 2
    assert (tmp_path / "src" / "notes_tool.py").exists()


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
