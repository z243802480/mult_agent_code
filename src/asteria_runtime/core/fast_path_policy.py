from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


LOW_RISK_KINDS = {"doc_update", "simple_file", "single_file_bugfix"}
HIGH_RISK_SIGNALS = (
    ".env",
    "secret",
    "secrets/",
    "private key",
    "id_rsa",
    "id_ed25519",
    "deploy",
    "production",
    "push",
    "payment",
    "auth",
    "permission",
    "sandbox",
    "merge",
    "rollback",
    "删除",
    "密钥",
    "权限",
    "生产",
    "部署",
)
DOC_SIGNALS = (
    "doc",
    "docs",
    "documentation",
    "readme",
    "markdown",
    "runbook",
    "说明",
    "文档",
    "手册",
)
SIMPLE_FILE_SIGNALS = (
    "create a file",
    "write a file",
    "single file",
    "one file",
    "local file",
    "生成文件",
    "创建文件",
    "写入文件",
    "单文件",
)
BUGFIX_SIGNALS = (
    "fix",
    "bug",
    "failing test",
    "pytest",
    "修复",
    "报错",
    "失败测试",
)
COMPLEX_SIGNALS = (
    "architecture",
    "orchestrator",
    "runtime",
    "subagent",
    "parallel",
    "multi-agent",
    "cross-module",
    "refactor",
    "架构",
    "运行时",
    "并行",
    "多智能体",
    "跨模块",
    "重构",
)


@dataclass(frozen=True)
class FastPathPolicy:
    task_kind: str
    risk: str
    goal_spec_tier: str
    review_tier: str
    context_mode: str
    deterministic_first: bool
    strong_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_fast_path(goal: str, *, target_files: list[str] | None = None) -> FastPathPolicy:
    text = " ".join([goal, " ".join(target_files or [])]).lower()
    files = [_normalize_path(item) for item in target_files or [] if item]
    if _has_high_risk_signal(text, files):
        return FastPathPolicy(
            task_kind="high_risk",
            risk="high",
            goal_spec_tier="strong",
            review_tier="strong",
            context_mode="focused",
            deterministic_first=False,
            strong_allowed=True,
            reason="High-risk permission, secret, deploy, auth, merge, or destructive signal.",
        )
    if _is_doc_update(text, files):
        return FastPathPolicy(
            task_kind="doc_update",
            risk="low",
            goal_spec_tier="medium",
            review_tier="deterministic",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Documentation-only or markdown-like update can use fast path.",
        )
    if _is_single_file_bugfix(text, files):
        return FastPathPolicy(
            task_kind="single_file_bugfix",
            risk="medium",
            goal_spec_tier="medium",
            review_tier="deterministic_then_medium",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Single-file bugfix should verify deterministically before semantic review.",
        )
    if _is_simple_file_goal(text, files):
        return FastPathPolicy(
            task_kind="simple_file",
            risk="low",
            goal_spec_tier="medium",
            review_tier="deterministic",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Single simple file output can use deterministic-first fast path.",
        )
    if any(signal in text for signal in COMPLEX_SIGNALS) or len(files) > 3:
        return FastPathPolicy(
            task_kind="complex_change",
            risk="medium",
            goal_spec_tier="medium",
            review_tier="medium_then_strong_if_needed",
            context_mode="focused",
            deterministic_first=True,
            strong_allowed=True,
            reason="Complex or multi-file change keeps strong eligible but not default.",
        )
    return FastPathPolicy(
        task_kind="complex_change",
        risk="medium",
        goal_spec_tier="medium",
        review_tier="medium_then_strong_if_needed",
        context_mode="focused",
        deterministic_first=True,
        strong_allowed=True,
        reason="Default to medium first; escalate only when risk or verification requires it.",
    )


def _normalize_path(value: str) -> str:
    try:
        return Path(value).as_posix().lower()
    except Exception:  # noqa: BLE001 - path hints can be arbitrary model/user text
        return value.replace("\\", "/").lower()


def _has_high_risk_signal(text: str, files: list[str]) -> bool:
    return any(signal in text for signal in HIGH_RISK_SIGNALS) or any(
        _protected_path_hint(item) for item in files
    )


def _protected_path_hint(path: str) -> bool:
    return (
        path == ".env"
        or path.startswith(".env.")
        or path.startswith("secrets/")
        or path.endswith(".pem")
        or path.endswith(".key")
        or path.endswith("/id_rsa")
        or path.endswith("/id_ed25519")
    )


def _is_doc_update(text: str, files: list[str]) -> bool:
    if any(signal in text for signal in DOC_SIGNALS):
        codeish = any(signal in text for signal in ("src/", "implement", "代码", "实现"))
        return not codeish
    return bool(files) and all(
        path.endswith((".md", ".mdx", ".txt", ".rst")) or path.startswith("docs/")
        for path in files
    )


def _is_simple_file_goal(text: str, files: list[str]) -> bool:
    if len(files) == 1 and not any(signal in text for signal in COMPLEX_SIGNALS):
        return True
    return any(signal in text for signal in SIMPLE_FILE_SIGNALS)


def _is_single_file_bugfix(text: str, files: list[str]) -> bool:
    primary_targets = [path for path in files if not _test_or_directory_hint(path)]
    return len(primary_targets) == 1 and any(signal in text for signal in BUGFIX_SIGNALS)


def _test_or_directory_hint(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not name or "." not in name:
        return True
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or path.startswith("tests/")
        or "/tests/" in path
    )
