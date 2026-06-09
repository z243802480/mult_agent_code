from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from asteria_runtime.core.main_path import main_path_text_lines
from asteria_runtime.core.todo_view import todo_view_text_lines


def render_project_cockpit(
    status: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> str:
    status = status or {}
    generated_at = generated_at or _now_iso()
    main_path = status.get("main_path") if isinstance(status.get("main_path"), dict) else {}
    todo_view = status.get("todo_view") if isinstance(status.get("todo_view"), dict) else {}
    current_context = (
        status.get("current_context") if isinstance(status.get("current_context"), dict) else {}
    )
    runtime_progress = (
        status.get("runtime_progress") if isinstance(status.get("runtime_progress"), dict) else {}
    )
    latest_matrix = (
        status.get("latest_real_provider_matrix")
        if isinstance(status.get("latest_real_provider_matrix"), dict)
        else {}
    )

    lines: list[str] = [
        "# 项目驾驶舱",
        "",
        f"更新时间：{generated_at}",
        "",
        "这是一页式进度跟踪页。它从当前状态与证据文档渲染，目的是让你只看这一页，就能判断当前完成度、灰度项、主风险和下一步。",
        "",
        "如果本页和 `reports/`、`当前状态与路线.md`、`研发总计划.md` 冲突，以最新证据和当前状态页为准；本页只负责给出可执行的驾驶视图。",
        "",
        "## 1. 当前结论",
        "",
        "```text",
        str(status.get("summary") or status.get("conclusion") or "当前状态未记录。"),
        "```",
        "",
        "### 完成到什么程度",
        "",
        "| 维度 | 现状 |",
        "| --- | --- |",
        f"| 主链路 | {main_path.get('path') or 'Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop'} |",
        f"| 当前阶段 | {status.get('current_phase') or status.get('workflow_state') or 'unknown'} |",
        f"| 当前步骤 | {main_path.get('current_step') or '未记录'} |",
        f"| 证据链 | {status.get('recommended_next_command') or 'status / sessions / reports'} |",
        f"| 质量控制 | {runtime_progress.get('verification', {}).get('status') or 'unknown'} / {runtime_progress.get('loop', {}).get('exit_reason') or 'n/a'} |",
        f"| 灰度编排 | {current_context.get('execution_profile', {}).get('profile_name') or 'opt-in only'} |",
        "",
        "### 仍未收敛",
        "",
        "| 维度 | 当前状态 |",
        "| --- | --- |",
        f"| 当前阻塞 | {status.get('current_blocker') or 'none'} |",
        f"| 待决数量 | {status.get('pending_decision_count') or 0} |",
        f"| 最近失败 | {_summary_field(status.get('latest_failure'))} |",
        f"| 最新矩阵 | {_matrix_summary(latest_matrix)} |",
        f"| 路线健康 | {_summary_field(status.get('route_health'), key='status', fallback='unknown')} |",
        "",
        "## 2. 当前只看这几个指标",
        "",
        "1. strong 调用是否只随风险升级出现",
        "2. 总等待时间是否被压住",
        "3. medium execution / repair 是否下降",
        "4. 最终报告是否仍然可读",
        "5. slim / focused context 是否真的覆盖到目标任务",
        "",
        "## 3. 当前主风险",
        "",
    ]

    for item in _list_items(status.get("risks")):
        lines.append(f"1. {item}")
    if not _list_items(status.get("risks")):
        lines.extend(
            [
                "1. 路线漂移：旧结论容易被新文档或局部样本覆盖。",
                "2. 局部最优：某个任务样本变好，不代表主路径已稳定。",
                "3. 信息碎片化：报告、路线、验证各自说话，最后没人能判断真相。",
                "4. 实现偏航：为了修一个 case 继续加分支，最后把主路径弄复杂。",
            ]
        )

    lines.extend(
        [
            "",
            "## 4. 下一步只做什么",
            "",
            "### 只保留一条主线",
            "",
        ]
    )

    next_actions = _list_items(status.get("next_actions"))
    if next_actions:
        for action in next_actions[:4]:
            lines.append(f"- {action}")
    else:
        lines.extend(
            [
                "- 固定滚动小灰度：`doc/simple_file`、`single_file_bugfix`、`context-heavy maintenance`",
                "- 继续记录：strong 调用、总等待时间、medium execution、repair 次数、报告可读性",
                "- 对 `tool_use` 继续保持实验态，不升默认",
            ]
        )

    lines.extend(
        [
            "",
            "### 只做一类判断",
            "",
            "- 这轮有没有比上一轮更短的主路径",
            "- 这轮有没有更少的强模型介入",
            "- 这轮有没有更少的 repair 和二次执行",
            "- 这轮最终报告是不是更容易读",
            "",
            "## 5. 当前主路径",
            "",
            *main_path_text_lines(main_path),
            "",
            "## 6. Todo 视图",
            "",
            *todo_view_text_lines(todo_view),
            "",
            "## 7. 使用方式",
            "",
            "每次跟进只问这四句：",
            "",
            "1. 现在完成到哪了？",
            "2. 最大风险变了没有？",
            "3. 最新证据支持什么？",
            "4. 下一步唯一该做什么？",
            "",
            "本页由 `scripts/write_project_cockpit.py` 生成，可随当前状态与证据重建。",
            "",
            "## 8. 参考来源",
            "",
            "- [文档体系总览](./文档体系总览.md)",
            "- [当前状态与路线](./当前状态与路线.md)",
            "- [真实模型验收](./真实模型验收.md)",
            "- [研发总计划](./研发总计划.md)",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _list_items(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        text = ""
        if isinstance(value, dict):
            text = str(value.get("summary") or value.get("title") or value.get("content") or "").strip()
        else:
            text = str(value).strip()
        if text:
            items.append(text)
    return items


def _matrix_summary(matrix: dict[str, Any]) -> str:
    if not matrix:
        return "none"
    summary = matrix.get("summary")
    if summary:
        return str(summary)
    cases = matrix.get("cases")
    if isinstance(cases, list):
        return f"{len(cases)} case(s)"
    return "available"


def _summary_field(value: object, *, key: str = "summary", fallback: str = "none") -> str:
    if isinstance(value, dict):
        field = value.get(key)
        if field:
            return str(field)
    return fallback


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
