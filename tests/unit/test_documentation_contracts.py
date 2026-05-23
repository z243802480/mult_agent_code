from __future__ import annotations

import re
from pathlib import Path


def test_readme_points_to_existing_chinese_source_of_truth() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    match = re.search(r"`(docs/zh/[^`]+\.md)`", readme)

    assert match, "README should link to the Chinese current-state source of truth."
    assert "当前状态" in match.group(1)
    assert Path(match.group(1)).exists()
    assert "slash-prefixed forms" in readme
    assert "compatibility aliases" in readme


def test_runtime_command_docs_describe_accept_workflow_and_alias_policy() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")

    required_fragments = [
        "命令示例优先使用无斜杠形式",
        "init -> run -> status -> resume -> review -> accept",
        "### 3.8 `/accept`",
        "不等同于用于测试套件的 `acceptance`",
        "asteria accept --no-promote",
        "status=completed",
        "current_phase=ACCEPTED",
        "run_accepted",
        "DecisionPoint",
    ]

    for fragment in required_fragments:
        assert fragment in docs


def test_runtime_command_docs_keep_user_workflow_sections_in_order() -> None:
    docs = Path("docs/zh/运行命令.md").read_text(encoding="utf-8")
    headings = [
        "### 3.6.1 `/resume`",
        "### 3.7 `/review`",
        "### 3.8 `/accept`",
        "### 3.9 `/debug`",
        "### 3.10 `/handoff`",
    ]

    positions = [docs.index(heading) for heading in headings]

    assert positions == sorted(positions)
    assert docs.count("### 3.8 ") == 1
