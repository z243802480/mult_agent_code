import json
from pathlib import Path

from asteria_runtime.commands.studio_benchmark_command import StudioBenchmarkCommand


def write_session(root: Path, session_id: str, events: list[dict]) -> None:
    session_dir = root / ".asteria" / "studio" / "sessions" / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def write_user_progress(root: Path, run_id: str, events: list[dict]) -> None:
    run_dir = root / ".asteria" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "user_progress.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def write_manifest(root: Path) -> Path:
    manifest = root / "benchmarks" / "studio_user_tasks.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "minimum_ready_score": 0.8,
                "required_user_progress_kinds": [
                    "plan",
                    "tool_use",
                    "tool_result",
                    "file_change",
                    "verification",
                    "final",
                ],
                "tasks": [
                    {
                        "id": "travel",
                        "goal": "帮我计划青岛旅行",
                        "required_events": ["user_message"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def test_studio_benchmark_passes_for_user_task_thread(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-ok",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {"type": "tool_start", "summary": "runtime", "display_level": "inspector"},
            {"type": "permission_request", "summary": "需要权限"},
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )
    write_user_progress(
        tmp_path,
        "run-1",
        semantic_progress_events(),
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()

    assert result.ok is True
    assert result.evaluated_sessions == 1
    assert result.score >= 0.8


def test_studio_benchmark_counts_runtime_user_progress_kinds(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-ok",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {"type": "permission_request", "summary": "需要权限"},
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )
    write_user_progress(
        tmp_path,
        "run-1",
        semantic_progress_events()
        + [
            {
                "channel": "model",
                "event_type": "delta",
                "display_level": "inspector",
                "transcript_kind": "diagnostic",
                "content_delta": "<think>raw planning stays inspectable only</think>",
            }
        ],
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert result.user_progress_events == 7
    assert checks["user_progress_protocol"]["ok"] is True
    assert checks["user_progress_semantic_contract"]["ok"] is True
    assert checks["process_kind_coverage"]["ok"] is True
    assert checks["main_thread_no_raw_model_delta"]["ok"] is True
    assert checks["inspector_model_delta_boundary"]["ok"] is True


def test_studio_benchmark_manifest_covers_loop_profiles() -> None:
    manifest = json.loads(
        (Path.cwd() / "benchmarks" / "studio_user_tasks.json").read_text(encoding="utf-8")
    )

    categories = {task["category"] for task in manifest["tasks"]}

    assert {"research", "brainstorm", "multi_agent"}.issubset(categories)


def test_studio_benchmark_rejects_process_log_as_final_answer(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-bad-final",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {
                "type": "final_answer",
                "summary": "工作过程",
                "content_delta": "## 工作过程\n- model stream\n\n# Final Report\n- run.json\n- task_plan.json",
            },
        ],
    )
    write_user_progress(tmp_path, "run-1", semantic_progress_events())

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert checks["final_answer_quality"]["ok"] is False
    assert any("final answers begin with the answer" in item for item in result.recommendations)


def test_studio_benchmark_rejects_raw_model_delta_in_main_thread(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-raw-main",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {
                "type": "model_delta",
                "summary": "raw",
                "content_delta": "<think>{\"schema_version\":\"0.1\"}</think>",
                "display_level": "main",
            },
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )
    write_user_progress(
        tmp_path,
        "run-1",
        semantic_progress_events()
        + [
            {
                "channel": "model",
                "event_type": "delta",
                "display_level": "main",
                "transcript_kind": "assistant_message",
                "content_delta": "<think>raw provider trace</think>",
            }
        ],
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert checks["main_thread_no_raw_model_delta"]["ok"] is False
    assert checks["inspector_model_delta_boundary"]["ok"] is False
    assert any("raw model deltas" in item.lower() for item in result.recommendations)


def test_studio_benchmark_ignores_legacy_user_progress_without_transcript_kind(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-ok",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )
    write_user_progress(
        tmp_path,
        "legacy-run",
        [
            {
                "channel": "model",
                "event_type": "delta",
                "display_level": "main",
                "content_delta": "<think>legacy raw model text</think>",
            }
        ],
    )
    write_user_progress(tmp_path, "modern-run", semantic_progress_events())

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert checks["main_thread_no_raw_model_delta"]["ok"] is True
    assert checks["inspector_model_delta_boundary"]["ok"] is True


def test_studio_benchmark_scopes_user_progress_by_run_id(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-ok",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )
    write_user_progress(
        tmp_path,
        "bad-modern-run",
        [
            {
                "channel": "model",
                "event_type": "delta",
                "display_level": "main",
                "transcript_kind": "assistant_message",
                "content_delta": "<think>bad run should not affect scoped check</think>",
            }
        ],
    )
    write_user_progress(tmp_path, "good-modern-run", semantic_progress_events())

    result = StudioBenchmarkCommand(
        tmp_path,
        manifest=manifest,
        run_id="good-modern-run",
    ).run()
    checks = {check["name"]: check for check in result.checks}

    assert result.user_progress_events == 6
    assert result.ok is True
    assert result.to_dict()["scope"] == "run:good-modern-run"
    assert checks["process_kind_coverage"]["ok"] is True
    assert checks["main_thread_no_raw_model_delta"]["ok"] is True
    assert checks["inspector_model_delta_boundary"]["ok"] is True


def test_studio_benchmark_run_scope_does_not_require_studio_session(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "legacy-bad-session",
        [
            {
                "type": "model_delta",
                "display_level": "main",
                "content_delta": "<think>legacy session raw text</think>",
            }
        ],
    )
    write_user_progress(tmp_path, "good-modern-run", semantic_progress_events())

    result = StudioBenchmarkCommand(
        tmp_path,
        manifest=manifest,
        run_id="good-modern-run",
    ).run()
    check_names = {check["name"] for check in result.checks}

    assert result.ok is True
    assert result.evaluated_sessions == 0
    assert "session_activity" not in check_names
    assert "benchmark_task_coverage" not in check_names
    assert "Run the Studio benchmark tasks" not in "\n".join(result.recommendations)


def test_studio_benchmark_run_scope_blocks_bad_runtime_contract(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_user_progress(
        tmp_path,
        "bad-modern-run",
        [
            {
                "channel": "model",
                "event_type": "delta",
                "display_level": "main",
                "transcript_kind": "assistant_message",
                "content_delta": "<think>raw provider trace</think>",
            }
        ],
    )

    result = StudioBenchmarkCommand(
        tmp_path,
        manifest=manifest,
        run_id="bad-modern-run",
    ).run()

    assert result.ok is False
    assert any(check["name"] == "main_thread_no_raw_model_delta" and not check["ok"] for check in result.checks)
    assert any(check["name"] == "process_kind_coverage" and not check["ok"] for check in result.checks)


def test_studio_benchmark_fails_without_session_events(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()

    assert result.ok is False
    assert result.evaluated_sessions == 0
    assert "Run the Studio benchmark tasks" in result.recommendations[0]


def semantic_progress_events() -> list[dict]:
    return [
        {
            "channel": "progress",
            "event_type": "start",
            "display_level": "main",
            "transcript_kind": "plan",
            "title": "Plan started",
            "summary": "Asteria is turning the goal into a plan.",
        },
        {
            "channel": "tool",
            "event_type": "tool_call",
            "display_level": "main",
            "transcript_kind": "tool_use",
            "title": "Reading files",
            "summary": "Inspecting the workspace before editing.",
        },
        {
            "channel": "tool",
            "event_type": "tool_observation",
            "display_level": "main",
            "transcript_kind": "tool_result",
            "title": "Read complete",
            "summary": "Relevant files were inspected.",
        },
        {
            "channel": "file",
            "event_type": "file_changed",
            "display_level": "main",
            "transcript_kind": "file_change",
            "title": "Files changed",
            "summary": "One file was updated.",
        },
        {
            "channel": "validation",
            "event_type": "validation_result",
            "display_level": "main",
            "transcript_kind": "verification",
            "title": "Verification passed",
            "summary": "The focused checks passed.",
        },
        {
            "channel": "conclusion",
            "event_type": "final_report",
            "display_level": "main",
            "transcript_kind": "final",
            "title": "Result",
            "summary": "The user-facing result is ready.",
        },
    ]
