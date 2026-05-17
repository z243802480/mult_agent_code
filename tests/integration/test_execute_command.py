import json
from pathlib import Path

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


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
                                "path": "docs/gray_batch_note.md",
                                "content": "# Gray Batch\n\n- Verify document-only tasks.\n",
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
                                    'paths=["docs/gray_batch_note.md"]; print(paths)"'
                                )
                            },
                            "reason": "this malformed command should be replaced",
                        }
                    ],
                    "completion_notes": "docs/gray_batch_note.md contains the gray batch note",
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

    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 2
    assert cost_report["tool_calls"] == 3
    assert cost_report["estimated_input_tokens"] == 25
    assert cost_report["estimated_output_tokens"] == 45


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
    plan = PlanCommand(tmp_path, "create a gray batch note", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    task_plan["tasks"][0].update(
        {
            "title": "Write gray batch note",
            "description": "Create docs/gray_batch_note.md with a short checklist.",
            "allowed_tools": ["write_file", "run_command"],
            "expected_artifacts": ["docs/gray_batch_note.md"],
            "expected_changed_files": ["docs/gray_batch_note.md"],
            "write_scope": ["docs/gray_batch_note.md"],
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
    assert (tmp_path / "docs" / "gray_batch_note.md").read_text(encoding="utf-8").startswith(
        "# Gray Batch"
    )
    validation_results = [
        json.loads(line)
        for line in (run_dir / "validation_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(validation_results) == 1
    assert "missing or empty" in validation_results[0]["command"]
    assert "docs/gray_batch_note.md" in validation_results[0]["command"]
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
