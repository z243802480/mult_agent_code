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
                "required_user_progress_channels": ["model", "tool", "file", "evidence"],
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
            {"type": "reasoning_delta", "summary": "制定计划", "display_level": "main"},
            {"type": "tool_start", "summary": "runtime", "display_level": "inspector"},
            {"type": "permission_request", "summary": "需要权限"},
            {
                "type": "final_answer",
                "summary": "答案",
                "content_delta": "## 答案\n已经生成青岛旅行计划。\n\n## 下一步\n可以继续细化预算。",
            },
        ],
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()

    assert result.ok is True
    assert result.evaluated_sessions == 1
    assert result.score >= 0.8


def test_studio_benchmark_counts_runtime_user_progress_channels(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-ok",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {"type": "reasoning_delta", "summary": "制定计划", "display_level": "main"},
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
        [
            {"channel": "model"},
            {"channel": "tool"},
            {"channel": "file"},
            {"channel": "evidence"},
        ],
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert result.user_progress_events == 4
    assert checks["user_progress_protocol"]["ok"] is True
    assert checks["process_channel_coverage"]["ok"] is True


def test_studio_benchmark_rejects_process_log_as_final_answer(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    write_session(
        tmp_path,
        "session-bad-final",
        [
            {"type": "user_message", "summary": "帮我计划青岛旅行"},
            {"type": "assistant_delta", "summary": "理解目标"},
            {"type": "reasoning_delta", "summary": "制定计划", "display_level": "main"},
            {
                "type": "final_answer",
                "summary": "工作过程",
                "content_delta": "## 工作过程\n- model stream\n\n# Final Report\n- run.json\n- task_plan.json",
            },
        ],
    )

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()
    checks = {check["name"]: check for check in result.checks}

    assert checks["final_answer_quality"]["ok"] is False
    assert any("final answers begin with the answer" in item for item in result.recommendations)


def test_studio_benchmark_fails_without_session_events(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)

    result = StudioBenchmarkCommand(tmp_path, manifest=manifest).run()

    assert result.ok is False
    assert result.evaluated_sessions == 0
    assert "Run the Studio benchmark tasks" in result.recommendations[0]
