import json
from pathlib import Path

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def validator() -> SchemaValidator:
    return SchemaValidator(Path.cwd() / "schemas")


def test_context_loader_includes_small_workspace_files_and_skips_secrets(tmp_path: Path) -> None:
    (tmp_path / ".asteria" / "context").mkdir(parents=True)
    (tmp_path / "buggy_math.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "api.txt").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")

    context = ContextLoader(tmp_path, validator()).load()

    files = {item["path"]: item for item in context["workspace_files"]}
    assert files["buggy_math.py"]["content"] == "def add(a, b):\n    return a - b\n"
    assert files["notes.md"]["content"] == "# Notes\n"
    assert "secrets/api.txt" not in files
    assert ".env" not in files


def test_workspace_files_rescan_reflects_files_written_after_load(tmp_path: Path) -> None:
    # ADR-0024 §5 #1: workspace_files() is a standalone re-scan so a later task sees files an earlier
    # task in the same run already wrote. The run-start load() snapshot must NOT be what a later task
    # reads; a fresh workspace_files() call must pick up the new file.
    (tmp_path / ".asteria").mkdir(parents=True)
    (tmp_path / "first.py").write_text("x = 1\n", encoding="utf-8")
    loader = ContextLoader(tmp_path, validator())

    at_run_start = {item["path"] for item in loader.load()["workspace_files"]}
    assert "first.py" in at_run_start
    assert "second.py" not in at_run_start

    # An earlier task writes a new file mid-run.
    (tmp_path / "second.py").write_text("y = 2\n", encoding="utf-8")

    refreshed = {item["path"]: item for item in loader.workspace_files()}
    assert "second.py" in refreshed, "per-task re-scan must see files written after run start"
    assert refreshed["second.py"]["content"] == "y = 2\n"


def test_context_loader_skips_stale_memory_rows(tmp_path: Path) -> None:
    schema_validator = validator()
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "failures.jsonl").write_text(
        json.dumps({"schema_version": "0.1.0", "content": "old row missing memory_id"})
        + "\n"
        + json.dumps(
            {
                "schema_version": "0.1.0",
                "memory_id": "memory-0001",
                "type": "failure_lesson",
                "content": "Keep validation probes scoped.",
                "source": {"kind": "test"},
                "tags": ["validation"],
                "confidence": 0.8,
                "created_at": "2026-06-01T00:00:00+08:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    context = ContextLoader(tmp_path, schema_validator).load()

    assert len(context["memory"]) == 1
    row = context["memory"][0]
    assert row["summary"] == "Keep validation probes scoped."
    assert row["truncated"] is False
    assert row["memory_id"] == "memory-0001"
    assert row["source_file"] == "failures.jsonl"


def _memory_row(memory_id: str, content: str, created_at: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "memory_id": memory_id,
        "type": "experiment_lesson",
        "content": content,
        "source": {"kind": "test"},
        "tags": ["lesson"],
        "confidence": 0.8,
        "created_at": created_at,
    }


def test_memory_index_dedupes_identical_content_and_truncates_long_entries(
    tmp_path: Path,
) -> None:
    # The memory feed is an INDEX now: many cheap one-line rows instead of the newest 8 full
    # texts. Append-only files re-learn the same lesson across runs, so identical content is
    # deduped (newest wins) and long entries are truncated with a flag telling the model to
    # fetch the full text via recall_memory.
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True)
    long_content = "A" * 500
    rows = [
        _memory_row("memory-0001", "Same lesson.", "2026-06-01T00:00:00+08:00"),
        _memory_row("memory-0002", "Same lesson.", "2026-06-02T00:00:00+08:00"),
        _memory_row("note-0001", long_content, "2026-06-03T00:00:00+08:00"),
    ]
    (memory_dir / "model_notes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    memory = ContextLoader(tmp_path, validator()).load()["memory"]

    assert [row["memory_id"] for row in memory] == ["memory-0002", "note-0001"]
    assert memory[0]["truncated"] is False
    assert memory[1]["truncated"] is True
    assert memory[1]["summary"] == "A" * 200


def test_memory_index_keeps_newest_entries_within_limit(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True)
    rows = [
        _memory_row(f"note-{index:04d}", f"Lesson {index}", f"2026-06-0{index}T00:00:00+08:00")
        for index in range(1, 6)
    ]
    (memory_dir / "model_notes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    memory = ContextLoader(tmp_path, validator(), memory_limit=2).load()["memory"]

    assert [row["memory_id"] for row in memory] == ["note-0004", "note-0005"]


def test_memory_index_reserves_newest_entry_per_source_file(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True)
    claude_rows = [
        _memory_row(
            f"claude-{index:04d}",
            f"Claude lesson {index}",
            f"2026-07-0{index}T00:00:00+08:00",
        )
        for index in range(1, 6)
    ]
    codex_rows = [
        _memory_row("codex-0001", "Codex project operating lesson.", "2026-06-01T00:00:00+08:00")
    ]
    (memory_dir / "claude_import.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in claude_rows), encoding="utf-8"
    )
    (memory_dir / "codex_import.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in codex_rows), encoding="utf-8"
    )

    memory = ContextLoader(tmp_path, validator(), memory_limit=3).load()["memory"]

    assert [row["memory_id"] for row in memory] == ["codex-0001", "claude-0004", "claude-0005"]
    assert {row["source_file"] for row in memory} == {
        "claude_import.jsonl",
        "codex_import.jsonl",
    }


def test_context_loader_feeds_back_active_goal_memory(tmp_path: Path) -> None:
    # The runtime writes ActiveGoalMemory after each run but historically never fed it back to the
    # executing model, so a resumed run started blind and re-did work / re-wrote files. The loader
    # must surface a bounded projection (prior goal, completed work, artifacts already produced).
    ActiveGoalMemory(tmp_path).write_from_run(
        goal_spec={"goal_id": "g1", "normalized_goal": "Build a snake game"},
        task_plan={
            "tasks": [
                {"task_id": "t0", "title": "Create snake.py", "status": "done", "summary": "done"},
                {"task_id": "t1", "title": "Add scoring", "status": "todo", "summary": ""},
            ]
        },
        run_status={"run_id": "run-1", "current_phase": "IMPLEMENTED"},
        review_status="unknown",
        completion="implemented_needs_review",
        artifacts=["snake.py"],
    )
    # The artifact has to actually exist for the loader to report it as produced: the projection
    # now reconciles recorded refs against the filesystem rather than repeating the claim.
    (tmp_path / "snake.py").write_text("# snake\n", encoding="utf-8")

    context = ContextLoader(tmp_path, validator()).load()

    active_goal = context["active_goal"]
    assert active_goal["current_goal"] == "Build a snake game"
    assert "snake.py" in active_goal["artifacts_already_produced"]
    assert active_goal["artifacts_recorded_but_missing"] == []
    assert any("Create snake.py" in item or "done" in item for item in active_goal["completed_work"])
    assert {"title": "Create snake.py", "status": "done"} in active_goal["overall_plan"]


def test_context_loader_active_goal_is_empty_without_memory(tmp_path: Path) -> None:
    (tmp_path / ".asteria").mkdir(parents=True)

    context = ContextLoader(tmp_path, validator()).load()

    assert context["active_goal"] == {}


def test_context_loader_surfaces_root_guidance_and_dedupes_it_from_workspace_files(
    tmp_path: Path,
) -> None:
    # The project's own AGENTS.md guidance must reach the executing model deliberately (with a
    # generous budget), not merely leak in truncated via the 20-file workspace snapshot. It must NOT
    # also appear in workspace_files (no duplicated content, no wasted slot). (ADR-0024 §5 #3)
    (tmp_path / "AGENTS.md").write_text("# Project rules\nStay in scope.\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    context = ContextLoader(tmp_path, validator()).load()

    assert context["root_guidance"]["path"] == "AGENTS.md"
    assert "Stay in scope." in context["root_guidance"]["content"]
    workspace_paths = {item["path"] for item in context["workspace_files"]}
    assert "AGENTS.md" not in workspace_paths
    assert "app.py" in workspace_paths


def test_context_loader_root_guidance_is_empty_without_agents_md(tmp_path: Path) -> None:
    (tmp_path / ".asteria").mkdir(parents=True)

    context = ContextLoader(tmp_path, validator()).load()

    assert context["root_guidance"] == {}


def test_context_loader_includes_bounded_acceptance_failure_evidence(tmp_path: Path) -> None:
    schema_validator = validator()
    failures_dir = tmp_path / ".asteria" / "acceptance" / "failures"
    failures_dir.mkdir(parents=True)
    store = JsonStore(schema_validator)
    for index in range(3):
        scenario = f"scenario_{index}"
        store.write(
            failures_dir / f"{scenario}.json",
            {
                "schema_version": "0.1.0",
                "evidence_id": f"acceptance-failure-{scenario}",
                "suite": "core",
                "scenario": scenario,
                "failure_summary": f"failure {index}",
                "acceptance_report": str(
                    tmp_path / ".asteria" / "acceptance" / "acceptance_report.json"
                ),
                "summary_json": str(tmp_path / "summary.json"),
                "workspace": str(tmp_path / scenario),
                "transcript": str(tmp_path / scenario / "transcript.json"),
                "expected_file": str(tmp_path / scenario / "artifact.py"),
                "stdout_tail": "",
                "stderr_tail": "missing artifact",
                "reproduce": {
                    "cli": f"python -m asteria_runtime /acceptance --scenario {scenario}",
                    "script": f"python scripts/real_model_acceptance.py --scenario {scenario}",
                },
                "promoted_task_id": f"task-000{index}",
                "created_at": f"2026-05-05T00:00:0{index}+08:00",
            },
            "acceptance_failure_evidence",
        )

    context = ContextLoader(
        tmp_path,
        schema_validator,
        acceptance_failure_limit=2,
    ).load()

    failures = context["acceptance_failures"]
    assert [failure["scenario"] for failure in failures] == ["scenario_1", "scenario_2"]
    assert failures[0]["evidence_path"] == ".asteria/acceptance/failures/scenario_1.json"
    assert failures[1]["failure_summary"] == "failure 2"
    assert failures[1]["reproduce"]["cli"].endswith("--scenario scenario_2")


def test_context_loader_includes_bounded_task_failure_evidence(tmp_path: Path) -> None:
    schema_validator = validator()
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    store = JsonlStore(schema_validator)
    for index in range(3):
        store.append(
            run_dir / "task_failures.jsonl",
            {
                "schema_version": "0.1.0",
                "evidence_id": f"task-failure-{index}",
                "run_id": "run-1",
                "task_id": f"task-000{index}",
                "phase": "execute",
                "failure_type": "contract_violation",
                "summary": f"failure {index}",
                "task_status": "blocked",
                "contract_check": {"violations": ["verification did not pass"]},
                "tool_failures": [],
                "verification_failures": [],
                "candidate": {},
                "recommendations": ["repair verification"],
                "created_at": f"2026-05-05T00:00:0{index}+08:00",
            },
            "task_failure_evidence",
        )

    context = ContextLoader(tmp_path, schema_validator, task_failure_limit=2).load("run-1")

    failures = context["task_failures"]
    assert [failure["task_id"] for failure in failures] == ["task-0001", "task-0002"]
    assert failures[0]["contract_check"]["violations"] == ["verification did not pass"]
    assert failures[1]["recommendations"] == ["repair verification"]


def test_context_loader_separates_artifacts_that_no_longer_exist(tmp_path: Path) -> None:
    # Nothing reconciled recorded artifact paths against the filesystem, so a file that was
    # reverted, moved, or never landed kept being handed to the doer as "already produced" — a
    # stale claim it had no way to check. Misses belong under their own key, not in the produced
    # list.
    ActiveGoalMemory(tmp_path).write_from_run(
        goal_spec={"goal_id": "g1", "normalized_goal": "Build a snake game"},
        task_plan={"tasks": [{"task_id": "t0", "title": "Create files", "status": "done"}]},
        run_status={"run_id": "run-1", "current_phase": "IMPLEMENTED"},
        review_status="unknown",
        completion="implemented_needs_review",
        artifacts=["snake.py", "reverted.py"],
    )
    (tmp_path / "snake.py").write_text("# snake\n", encoding="utf-8")

    active_goal = ContextLoader(tmp_path, validator()).load()["active_goal"]

    assert active_goal["artifacts_already_produced"] == ["snake.py"]
    assert active_goal["artifacts_recorded_but_missing"] == ["reverted.py"]
