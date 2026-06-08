from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

RiskTier = Literal["high", "default", "readonly"]

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

# Deprecated alias kinds — projected for telemetry/gate compatibility only.
DEPRECATED_TASK_KINDS = frozenset(
    {
        "high_risk",
        "doc_update",
        "simple_file",
        "single_file_bugfix",
        "complex_change",
    }
)


@dataclass(frozen=True)
class RiskTierPolicy:
    risk_tier: RiskTier
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FastPathPolicy:
    task_kind: str
    risk: str
    risk_tier: RiskTier
    goal_spec_tier: str
    review_tier: str
    context_mode: str
    deterministic_first: bool
    strong_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_risk_tier(
    goal: str,
    *,
    goal_spec: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    target_files: list[str] | None = None,
    parallel_writes: bool = False,
) -> RiskTierPolicy:
    explicit = _explicit_risk_tier(goal_spec, task)
    if explicit:
        return RiskTierPolicy(explicit, "Explicit risk_tier from goal or task contract.")
    if parallel_writes:
        return RiskTierPolicy("high", "Parallel writes require harness profile.")
    explicit_files = [_normalize_path(item) for item in target_files or [] if item]
    inferred_files = _file_hints_from_goal(goal)
    files = list(dict.fromkeys([*explicit_files, *inferred_files]))
    text = " ".join([goal, " ".join(files)]).lower()
    if _has_high_risk_signal(text, files):
        return RiskTierPolicy("high", "High-risk permission, secret, deploy, auth, merge, or destructive signal.")
    if task and _is_readonly_task(task):
        return RiskTierPolicy("readonly", "Task contract is readonly (no write scope).")
    return RiskTierPolicy("default", "Default orchestration tier.")


def classify_fast_path(
    goal: str,
    *,
    target_files: list[str] | None = None,
    goal_spec: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
) -> FastPathPolicy:
    risk = classify_risk_tier(
        goal,
        goal_spec=goal_spec,
        task=task,
        target_files=target_files,
    )
    return _project_fast_path(
        risk,
        goal=goal,
        target_files=target_files,
        goal_spec=goal_spec,
        task=task,
    )


def _project_fast_path(
    risk: RiskTierPolicy,
    *,
    goal: str,
    target_files: list[str] | None,
    goal_spec: dict[str, Any] | None,
    task: dict[str, Any] | None,
) -> FastPathPolicy:
    if risk.risk_tier == "high":
        return FastPathPolicy(
            task_kind="high_risk",
            risk="high",
            risk_tier="high",
            goal_spec_tier="strong",
            review_tier="strong",
            context_mode="focused",
            deterministic_first=False,
            strong_allowed=True,
            reason=risk.reason,
        )

    explicit_files = [_normalize_path(item) for item in target_files or [] if item]
    inferred_files = _file_hints_from_goal(goal)
    files = list(dict.fromkeys([*explicit_files, *inferred_files]))
    write_scope = _write_scope_paths(task)
    scoped_files = write_scope or files

    if risk.risk_tier == "readonly":
        return FastPathPolicy(
            task_kind="complex_change",
            risk="low",
            risk_tier="readonly",
            goal_spec_tier="medium",
            review_tier="deterministic",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason=risk.reason,
        )

    profile = task.get("fast_path_profile") if isinstance(task, dict) else None
    if isinstance(profile, dict):
        return _fast_path_from_profile(profile, risk_tier="default")

    planner_kind = str((task or {}).get("task_kind") or "").strip().lower()
    if _is_doc_artifact_scope(scoped_files):
        return FastPathPolicy(
            task_kind="doc_update",
            risk="low",
            risk_tier="default",
            goal_spec_tier="medium",
            review_tier="deterministic",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Documentation artifact scope from task contract.",
        )
    if planner_kind in {"diagnostic", "verification"} and _single_primary_target(scoped_files, task):
        return FastPathPolicy(
            task_kind="single_file_bugfix",
            risk="medium",
            risk_tier="default",
            goal_spec_tier="medium",
            review_tier="deterministic_then_medium",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Diagnostic task with single primary target from contract.",
        )
    if _single_primary_target(scoped_files, task):
        return FastPathPolicy(
            task_kind="simple_file",
            risk="low",
            risk_tier="default",
            goal_spec_tier="medium",
            review_tier="deterministic",
            context_mode="slim",
            deterministic_first=True,
            strong_allowed=False,
            reason="Single scoped artifact from task contract.",
        )
    if len(scoped_files) > 3:
        return _complex_default(reason="Multi-file scope from task contract.")

    explicit_tier = _explicit_review_tier(goal_spec, task)
    if explicit_tier == "strong":
        return _complex_default(reason="Explicit strong review tier on contract.", strong_default=True)

    return _complex_default(reason=risk.reason)


def _complex_default(*, reason: str, strong_default: bool = True) -> FastPathPolicy:
    return FastPathPolicy(
        task_kind="complex_change",
        risk="medium",
        risk_tier="default",
        goal_spec_tier="medium",
        review_tier="medium_then_strong_if_needed",
        context_mode="focused",
        deterministic_first=True,
        strong_allowed=strong_default,
        reason=reason,
    )


def _fast_path_from_profile(profile: dict[str, Any], *, risk_tier: RiskTier) -> FastPathPolicy:
    return FastPathPolicy(
        task_kind=str(profile.get("task_kind") or "default"),
        risk=str(profile.get("risk") or "medium"),
        risk_tier=risk_tier,
        goal_spec_tier=str(profile.get("goal_spec_tier") or "medium"),
        review_tier=str(profile.get("review_tier") or "medium_then_strong_if_needed"),
        context_mode=str(profile.get("context_mode") or "focused"),
        deterministic_first=bool(profile.get("deterministic_first", True)),
        strong_allowed=bool(profile.get("strong_allowed", True)),
        reason=str(profile.get("reason") or "Explicit fast_path_profile on task contract."),
    )


def _explicit_risk_tier(
    goal_spec: dict[str, Any] | None,
    task: dict[str, Any] | None,
) -> RiskTier | None:
    for source in (task, goal_spec):
        if not isinstance(source, dict):
            continue
        raw = str(source.get("risk_tier") or "").strip().lower()
        if raw in {"high", "default", "readonly"}:
            return raw  # type: ignore[return-value]
    return None


def _explicit_review_tier(
    goal_spec: dict[str, Any] | None,
    task: dict[str, Any] | None,
) -> str | None:
    for source in (task, goal_spec):
        if not isinstance(source, dict):
            continue
        raw = str(source.get("review_tier") or "").strip().lower()
        if raw:
            return raw
    return None


def _is_readonly_task(task: dict[str, Any]) -> bool:
    parallel_safety = str(task.get("parallel_safety") or "").strip().lower()
    if parallel_safety == "readonly":
        return True
    write_scope = task.get("write_scope")
    if isinstance(write_scope, list) and not write_scope:
        return task.get("write_allowed") is not True
    return False


def _write_scope_paths(task: dict[str, Any] | None) -> list[str]:
    if not isinstance(task, dict):
        return []
    paths: list[str] = []
    for item in task.get("write_scope") or []:
        if isinstance(item, str) and item.strip():
            paths.append(_normalize_path(item))
    for item in task.get("expected_artifacts") or []:
        if isinstance(item, str) and item.strip() and _looks_like_file_path(item):
            normalized = _normalize_path(item)
            if normalized not in paths:
                paths.append(normalized)
    return paths


def _is_doc_artifact_scope(files: list[str]) -> bool:
    concrete = [path for path in files if _looks_like_file_path(path)]
    if not concrete:
        return False
    return all(
        path.endswith((".md", ".mdx", ".txt", ".rst")) or path.startswith("docs/")
        for path in concrete
    )


def _single_primary_target(files: list[str], task: dict[str, Any] | None) -> bool:
    primary = [path for path in files if _looks_like_file_path(path) and not _test_or_directory_hint(path)]
    if len(primary) == 1:
        return True
    if not isinstance(task, dict):
        return False
    changed = [
        _normalize_path(str(item))
        for item in task.get("expected_changed_files") or []
        if isinstance(item, str) and _looks_like_file_path(item) and not _test_or_directory_hint(item)
    ]
    return len(changed) == 1


def _looks_like_file_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower().strip()
    if not normalized or normalized.endswith("/"):
        return False
    return "." in normalized.rsplit("/", 1)[-1]


def _normalize_path(value: str) -> str:
    try:
        return Path(value).as_posix().lower()
    except Exception:  # noqa: BLE001 - path hints can be arbitrary model/user text
        return value.replace("\\", "/").lower()


def _file_hints_from_goal(goal: str) -> list[str]:
    hints: list[str] = []
    for match in re.finditer(r"(?<![\w/.-])[\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]+(?![\w/.-])", goal):
        hints.append(_normalize_path(match.group(0)))
    return hints


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
