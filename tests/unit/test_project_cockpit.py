from __future__ import annotations

from asteria_runtime.core.project_cockpit import render_project_cockpit


def test_render_project_cockpit_uses_status_controls() -> None:
    payload = {
        "summary": "系统已经具备可运行的主链路，但仍处在收口和灰度校准阶段。",
        "current_phase": "Post-S73 Beta convergence",
        "workflow_state": "active",
        "current_blocker": "none",
        "pending_decision_count": 1,
        "recommended_next_command": "status",
        "current_context": {"execution_profile": {"profile_name": "session_agent"}},
        "main_path": {
            "path": "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop",
            "current_step": "Inspect latest evidence.",
        },
        "todo_view": {
            "summary": "2/3 complete; current item is single_file_bugfix.",
            "current": {"content": "single_file_bugfix"},
        },
        "runtime_progress": {
            "verification": {"status": "passed"},
            "loop": {"exit_reason": "completed"},
        },
        "latest_real_provider_matrix": {"summary": "4 cases; tool_use still gray."},
        "risks": [{"summary": "路线漂移"}],
        "next_actions": [{"summary": "固定滚动小灰度"}],
        "latest_failure": {"summary": "none"},
        "route_health": {"status": "healthy"},
    }

    text = render_project_cockpit(payload, generated_at="2026-06-09T00:00:00+00:00")

    assert "# 项目驾驶舱" in text
    assert "系统已经具备可运行的主链路" in text
    assert "Post-S73 Beta convergence" in text
    assert "session_agent" in text
    assert "single_file_bugfix" in text
    assert "路线漂移" in text
    assert "固定滚动小灰度" in text
    assert "scripts/write_project_cockpit.py" in text
