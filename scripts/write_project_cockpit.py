from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from asteria_runtime.core.project_cockpit import render_project_cockpit  # noqa: E402
from asteria_runtime.utils.time import now_iso  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the project cockpit from status")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/zh/项目驾驶舱.md"),
        help="Cockpit markdown output path",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else (root / args.output)
    output = output.resolve()
    status = build_project_snapshot(root)
    content = render_project_cockpit(status, generated_at=now_iso())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Wrote project cockpit: {output}")


def build_project_snapshot(root: Path) -> dict[str, object]:
    current_state = _read_text(root / "docs/zh/当前状态与路线.md")
    validation = _read_text(root / "docs/zh/真实模型验收.md")

    current_phase = _extract_marker(current_state, "ACTIVE_PHASE") or "Post-S73 Beta convergence"
    active_slice = _extract_marker(current_state, "ACTIVE_SLICE") or "S74"
    worker_transport = _extract_table_row(current_state, "Worker transport") or (
        "单文件 / 文档 fast path 试行 `tool_use`；仅在 native tool-call 支持的 provider route 上灰度。"
    )
    matrix_summary = _extract_latest_matrix_summary(validation) or (
        "rolling-fastpath-v1 still gray; single_file_bugfix may add medium execution/repair."
    )

    next_command = "real-model-smoke --matrix-preset rolling-fastpath-v1 --no-research --model-max-retries 0"

    return {
        "summary": (
            "系统已经具备可运行的本地-first 长任务 harness 主链路，"
            "但仍处在产品收口和灰度校准阶段，不适合再扩大复杂编排默认面。"
        ),
        "conclusion": "Project cockpit snapshot generated from current state docs.",
        "workflow_state": "active",
        "current_phase": current_phase,
        "current_blocker": worker_transport,
        "pending_decision_count": 1,
        "recommended_next_command": next_command,
        "current_context": {"execution_profile": {"profile_name": "session_agent"}},
        "main_path": {
            "path": "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop",
            "active_stage": "tool_use",
            "current_step": "Run the rolling small gray matrix and keep tool_use experimental.",
            "next_command": next_command,
        },
        "todo_view": {
            "summary": (
                f"ACTIVE_SLICE={active_slice}; continue doc/simple_file, "
                "single_file_bugfix, and context-heavy maintenance gray samples."
            ),
            "current": {"content": "single_file_bugfix", "status": "in_progress"},
        },
        "runtime_progress": {
            "verification": {"status": "passed"},
            "loop": {"exit_reason": "n/a"},
        },
        "latest_real_provider_matrix": {"summary": matrix_summary},
        "risks": [
            {"summary": "路线漂移：旧结论容易被新文档或局部样本覆盖。"},
            {"summary": "局部最优：某个任务样本变好，不代表主路径已稳定。"},
            {"summary": "信息碎片化：报告、路线、验证各自说话，最后没人能判断真相。"},
            {"summary": "实现偏航：为了修一个 case 继续加分支，最后把主路径弄复杂。"},
        ],
        "next_actions": [
            {"summary": "固定滚动小灰度：doc/simple_file、single_file_bugfix、context-heavy maintenance"},
            {"summary": "继续记录：strong 调用、总等待时间、medium execution、repair 次数、报告可读性"},
            {"summary": "对 tool_use 继续保持实验态，不升默认"},
        ],
        "latest_failure": {"summary": "none"},
        "route_health": {"status": "healthy"},
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_marker(text: str, marker: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{marker}：") or line.startswith(f"{marker}:"):
            value = line.split("：", 1)[-1] if "：" in line else line.split(":", 1)[-1]
            value = value.strip()
            return value or None
    return None


def _extract_table_row(text: str, heading: str) -> str | None:
    for line in text.splitlines():
        if f"| {heading} |" in line:
            parts = [part.strip() for part in line.strip().strip("|").split("|")]
            if len(parts) >= 2:
                return parts[1]
    return None


def _extract_latest_matrix_summary(text: str) -> str | None:
    for line in text.splitlines():
        if "2026-06-09 rolling `single_file_bugfix`" in line:
            return "2026-06-09 rolling `single_file_bugfix` still shows extra medium execution/repair."
    return None


if __name__ == "__main__":
    main()
