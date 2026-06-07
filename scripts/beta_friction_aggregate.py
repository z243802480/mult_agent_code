"""Aggregate Beta trial friction reports from docs/zh/reports/S14-beta-user-trial-*.md."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

STUDIO_FRICTION_BUCKETS = ("diff", "context", "session", "side_ask", "other")

_BUCKET_KEYWORD_PATTERNS: dict[str, list[str]] = {
    "diff": [
        r"diff",
        r"改动",
        r"对比",
        r"审查",
        r"git",
        r"split",
        r"stage",
        r"discard",
        r"看不清",
        r"diffreview",
        r"文件.*改",
        r"t\d\s*diff",
    ],
    "context": [
        r"context",
        r"上下文",
        r"compact",
        r"压力",
        r"token",
        r"budget",
        r"压缩",
        r"scope",
        r"范围",
        r"决策卡",
        r"decision",
    ],
    "session": [
        r"session",
        r"会话",
        r"切换",
        r"workspace",
        r"侧栏",
        r"rename",
        r"ctrl\+tab",
        r"多任务",
        r"worktree",
        r"recent",
    ],
    "side_ask": [
        r"side",
        r"侧聊",
        r"quick\s*ask",
        r"/ask",
        r"ctrl\+;",
        r"composer.*ask",
    ],
}


@dataclass
class TrialRecord:
    source: str
    date: str | None = None
    tester: str | None = None
    is_maintainer: bool | None = None
    total_minutes: str | None = None
    steps_passed: dict[str, bool] = field(default_factory=dict)
    goal_completed: bool | None = None
    review_completed: bool | None = None
    accept_completed: bool | None = None
    blockers: list[str] = field(default_factory=list)
    friction: dict[str, int] = field(default_factory=dict)
    studio_friction: dict[str, int] = field(default_factory=dict)


def _bool_from_cell(value: str) -> bool | None:
    text = value.strip().lower()
    if text in {"✅", "yes", "是", "true", "pass", "passed", "通过"}:
        return True
    if text in {"❌", "no", "否", "false", "fail", "failed", "未通过"}:
        return False
    return None


def _extract_field(text: str, label: str) -> str | None:
    pattern = rf"\|\s*{re.escape(label)}\s*\|\s*([^|\n]+?)\s*\|"
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1).strip()


def _parse_step_rows(text: str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for row in re.finditer(
        r"^\|\s*([A-Z]\d(?:–[A-Z]\d)?[^|]*?)\s*\|\s*([^|]*?)\s*\|",
        text,
        flags=re.MULTILINE,
    ):
        step = row.group(1).strip()
        if not re.match(r"^[A-Z]\d", step):
            continue
        passed = _bool_from_cell(row.group(2))
        if passed is not None:
            results[step] = passed
    return results


def _parse_blockers(text: str) -> list[str]:
    section = re.search(
        r"##\s*[45]\.?\s*阻塞与反馈([\s\S]*?)(?:\n##\s|\Z)",
        text,
        flags=re.IGNORECASE,
    )
    if not section:
        return []
    body = section.group(1)
    code_match = re.search(r"```(?:text)?\s*([\s\S]*?)```", body)
    if code_match:
        lines = [line.strip(" -•\t") for line in code_match.group(1).splitlines()]
        return [line for line in lines if line and line not in {"（最难的一步、报错、UX 问题）"}]
    lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
        elif line.startswith("* "):
            lines.append(line[2:].strip())
    return [line for line in lines if line]


def _empty_studio_buckets() -> dict[str, dict[str, object]]:
    return {bucket: {"score": 0, "items": []} for bucket in STUDIO_FRICTION_BUCKETS}


def classify_blocker_bucket(text: str) -> str:
    lowered = text.lower()
    for bucket in STUDIO_FRICTION_BUCKETS[:-1]:
        for pattern in _BUCKET_KEYWORD_PATTERNS[bucket]:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                return bucket
    return "other"


def _parse_studio_friction(text: str) -> dict[str, int]:
    explicit = re.search(
        r"studio\s*friction[^0-9]*"
        r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        keys = ("diff", "context", "session", "side_ask")
        return {key: int(explicit.group(index)) for index, key in enumerate(keys, start=1)}

    table_match = re.search(
        r"\|\s*Studio friction\s*\|\s*"
        r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*\|",
        text,
        flags=re.IGNORECASE,
    )
    if table_match:
        keys = ("diff", "context", "session", "side_ask")
        return {key: int(table_match.group(index)) for index, key in enumerate(keys, start=1)}

    per_bucket: dict[str, int] = {}
    for bucket in ("diff", "context", "session", "side_ask"):
        cell = re.search(
            rf"\|\s*{bucket}\s*\|\s*(\d+)\s*\|",
            text,
            flags=re.IGNORECASE,
        )
        if cell:
            per_bucket[bucket] = int(cell.group(1))
    return per_bucket


def aggregate_studio_buckets(records: list[TrialRecord]) -> dict[str, object]:
    buckets = _empty_studio_buckets()
    for record in records:
        for bucket, score in record.studio_friction.items():
            if bucket not in buckets:
                continue
            bucket_data = buckets[bucket]
            assert isinstance(bucket_data, dict)
            bucket_data["score"] = int(bucket_data["score"]) + score
            if score > 0:
                items = bucket_data["items"]
                assert isinstance(items, list)
                items.append(
                    {
                        "tester": record.tester or "unknown",
                        "score": score,
                        "source": record.source,
                    }
                )

        for blocker in record.blockers:
            bucket = classify_blocker_bucket(blocker)
            bucket_data = buckets[bucket]
            assert isinstance(bucket_data, dict)
            bucket_data["score"] = int(bucket_data["score"]) + 1
            items = bucket_data["items"]
            assert isinstance(items, list)
            items.append(
                {
                    "tester": record.tester or "unknown",
                    "text": blocker,
                    "source": record.source,
                }
            )

    ranked = sorted(
        ((bucket, int(data["score"])) for bucket, data in buckets.items() if bucket != "other"),
        key=lambda item: (-item[1], item[0]),
    )
    top_bucket = ranked[0][0] if ranked and ranked[0][1] > 0 else None
    return {
        "buckets": buckets,
        "top_bucket": top_bucket,
        "next_slice_rule": (
            f"open slice for `{top_bucket}` friction"
            if top_bucket
            else "defer — no Studio friction top bucket yet"
        ),
    }


def parse_trial_report(path: Path) -> TrialRecord:
    text = path.read_text(encoding="utf-8")
    maintainer_raw = _extract_field(text, "是否维护者")
    maintainer: bool | None = None
    if maintainer_raw:
        maintainer = "是" in maintainer_raw or "yes" in maintainer_raw.lower()

    record = TrialRecord(
        source=str(path.as_posix()),
        date=_extract_field(text, "日期"),
        tester=_extract_field(text, "测试者代号") or _extract_field(text, "测试者"),
        is_maintainer=maintainer,
        total_minutes=_extract_field(text, "合计") or _extract_field(text, "总耗时"),
        steps_passed=_parse_step_rows(text),
        blockers=_parse_blockers(text),
    )

    goal_raw = _extract_field(text, "Goal 是否独立完成") or _extract_field(text, "Goal 独立完成")
    review_raw = _extract_field(text, "Review 是否完成") or _extract_field(text, "Review")
    accept_raw = _extract_field(text, "Accept 是否完成") or _extract_field(text, "Accept")
    if goal_raw:
        record.goal_completed = _bool_from_cell(goal_raw)
    if review_raw:
        record.review_completed = _bool_from_cell(review_raw.split("·")[0])
    if accept_raw:
        record.accept_completed = _bool_from_cell(accept_raw.split("·")[0])

    friction_match = re.search(r"friction[^0-9]*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", text, flags=re.IGNORECASE)
    if friction_match:
        record.friction = {
            "decide": int(friction_match.group(1)),
            "debug": int(friction_match.group(2)),
            "resume": int(friction_match.group(3)),
        }
    record.studio_friction = _parse_studio_friction(text)
    return record


def aggregate_reports(report_dir: Path) -> dict[str, object]:
    reports = sorted(
        path
        for path in report_dir.glob("S14-beta-user-trial-*.md")
        if path.name != "S14-beta-user-trial-template.md"
    )
    records = [parse_trial_report(path) for path in reports]
    non_maintainer = [record for record in records if record.is_maintainer is False]
    completed_abc = [
        record
        for record in records
        if all(record.steps_passed.get(key, False) for key in ("A1–A5 安装 + Studio", "B1–B4 Goal 执行", "C1–C3 Review + Accept"))
        or (
            record.goal_completed
            and record.review_completed
            and record.accept_completed
        )
    ]

    blocker_counts: dict[str, int] = {}
    for record in records:
        for blocker in record.blockers:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    studio = aggregate_studio_buckets(records)
    return {
        "ok": True,
        "report_count": len(records),
        "non_maintainer_count": len(non_maintainer),
        "completed_abc_count": len(completed_abc),
        "top_blockers": sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))[:8],
        "studio_friction": studio,
        "records": [asdict(record) for record in records],
    }


def render_markdown(summary: dict[str, object]) -> str:
    lines = [
        "# Beta friction aggregate",
        "",
        f"- Reports: **{summary['report_count']}**",
        f"- Non-maintainer: **{summary['non_maintainer_count']}**",
        f"- Completed A/B/C: **{summary['completed_abc_count']}**",
        "",
        "## Top blockers",
        "",
    ]
    blockers = summary.get("top_blockers") or []
    if not blockers:
        lines.append("- (none recorded)")
    else:
        for text, count in blockers:
            lines.append(f"- ({count}×) {text}")
    lines.append("")
    studio = summary.get("studio_friction") or {}
    lines.extend(["## Studio friction buckets", ""])
    buckets = studio.get("buckets") or {}
    if not isinstance(buckets, dict):
        buckets = {}
    for bucket in STUDIO_FRICTION_BUCKETS:
        data = buckets.get(bucket) or {"score": 0, "items": []}
        score = data.get("score", 0) if isinstance(data, dict) else 0
        lines.append(f"- **{bucket}**: {score}")
    top_bucket = studio.get("top_bucket")
    next_rule = studio.get("next_slice_rule") or "defer"
    lines.append("")
    lines.append(f"- Top bucket: **{top_bucket or '(none)'}**")
    lines.append(f"- Next slice: **{next_rule}**")
    lines.append("")
    lines.append("## Records")
    lines.append("")
    for record in summary.get("records") or []:
        if not isinstance(record, dict):
            continue
        lines.append(
            f"- `{record.get('tester') or 'unknown'}` "
            f"({'maintainer' if record.get('is_maintainer') else 'beta'}) "
            f"steps={len(record.get('steps_passed') or {})} "
            f"blockers={len(record.get('blockers') or [])}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Aggregate Beta trial friction reports.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help="Directory containing S14-beta-user-trial-*.md (default: docs/zh/reports)",
    )
    parser.add_argument("--markdown", action="store_true", help="Print markdown summary")
    parser.add_argument("--write-md", type=Path, default=None, help="Write markdown summary to path")
    args = parser.parse_args()

    root = args.root.resolve()
    report_dir = (args.reports_dir or root / "docs" / "zh" / "reports").resolve()
    summary = aggregate_reports(report_dir)

    if args.write_md:
        args.write_md.parent.mkdir(parents=True, exist_ok=True)
        args.write_md.write_text(render_markdown(summary), encoding="utf-8")

    if args.markdown:
        print(render_markdown(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
