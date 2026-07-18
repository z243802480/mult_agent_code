from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def looks_like_file_path(value: str) -> bool:
    """Is this entry a concrete FILE the runtime can hold a task to — as opposed to a prose
    placeholder ("implementation artifact", "the new module") or a directory scope ("src/")?

    Single source of truth for every deterministic boundary that asks "did the expected file appear".
    Two structural rules, and deliberately no third:

    * **whitespace → prose.** The planner writes these entries in free text and no fixed vocabulary
      can enumerate them; a denylist of four exact strings (what this replaced) let the mere plural
      "implementation artifacts" through as a FILE that must change, failing tasks that did all their
      work. Real paths do not contain spaces here.
    * **trailing separator → directory scope, not a deliverable.** The model may legitimately write
      anywhere inside it, so demanding that "src/" itself "exist as a changed file" fails every task.

    **It does NOT require an extension.** Requiring one (the first cut of this function did) silently
    demotes `Makefile` / `Dockerfile` / `LICENSE` to "prose": the completion gate then stops enforcing
    them, and — worse — `write_scope` falls back to this list, so a task whose only deliverable is a
    Makefile gets an EMPTY write scope and cannot write anything at all. Under-enforcement here breaks
    the task outright; over-enforcement only costs the model another bounded round.

    A BARE token (no separator, no extension) is a filename only if it is ASCII — the `Makefile` /
    `Dockerfile` convention. Chinese prose carries no whitespace to give itself away ("更新后的文档"),
    so whitespace alone cannot separate it from a filename; a real Chinese path in this repo always
    has a separator or an extension (`docs/zh/研发总计划.md`) and is still recognized.
    """
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    if text.endswith("/") or text.endswith("\\"):
        return False
    if ("/" in text) or ("\\" in text) or ("." in Path(text).name):
        return True
    return text.isascii()


TASK_KINDS = {
    "diagnostic",
    "implementation",
    "verification",
    "research",
    "decision",
    "report",
    "ui",
}

DEFAULT_FAILURE_POLICY = "create_repair_task"


@dataclass(frozen=True)
class TaskContractCheck:
    ok: bool
    violations: list[str]
    changed_files: list[str]
    expected_changed_files: list[str]
    verification_total: int
    verification_passed: int
    # Disk-observed changes OUTSIDE the task's write_scope (e.g. written via shell, which the
    # tool-layer scope guard cannot see). Disclosure, not a violation: hard prevention is the
    # OS sandbox's job; app/test byproducts also land here and must not fail an honest task.
    unscoped_changed_files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "Task completion contract satisfied."
        return "Task completion contract violated: " + "; ".join(self.violations)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": self.violations,
            "changed_files": self.changed_files,
            "expected_changed_files": self.expected_changed_files,
            "verification_total": self.verification_total,
            "verification_passed": self.verification_passed,
            "unscoped_changed_files": self.unscoped_changed_files,
        }


def task_kind(task: dict) -> str:
    explicit = str(task.get("task_kind") or "").strip().lower()
    if explicit in TASK_KINDS:
        return explicit
    return infer_task_kind(task)


def infer_task_kind(task: dict) -> str:
    text = _task_text(task)
    if any(marker in text for marker in {"decision", "approve", "choose", "select option"}):
        return "decision"
    if any(marker in text for marker in {"research", "investigate", "survey", "source"}):
        return "research"
    if any(marker in text for marker in {"report", "readme", "documentation", "summary"}):
        return "report"
    if any(marker in text for marker in {"ui", "web page", "interface", "dashboard"}):
        return "ui"
    if any(
        marker in text
        for marker in {
            "baseline failure",
            "capture failing",
            "diagnose",
            "failing tests",
            "failures reported",
            "identify failing",
            "identify which tests",
            "locate",
            "run pytest",
            "run tests",
        }
    ):
        return "diagnostic"
    if any(marker in text for marker in {"verify", "verification", "test pass", "tests pass"}):
        return "verification"
    return "implementation"


def completion_contract(task: dict) -> dict:
    contract = task.get("completion_contract")
    if isinstance(contract, dict):
        return contract
    kind = task_kind(task)
    return {
        "requires_changed_artifact": kind in {"implementation", "report", "ui"},
        "requires_verification": kind
        in {"diagnostic", "implementation", "verification", "report", "ui"},
        "allows_expected_failure": kind == "diagnostic",
    }


def read_scope(task: dict) -> list[str]:
    explicit = task.get("read_scope")
    if isinstance(explicit, list):
        return _string_list(explicit)
    return _default_read_scope(task)


def write_scope(task: dict) -> list[str]:
    explicit = task.get("write_scope")
    if isinstance(explicit, list):
        return _string_list(explicit)
    expected = _expected_changed_files(task)
    if expected:
        return expected
    if task_kind(task) in {"research", "decision", "verification", "diagnostic"}:
        return []
    return _string_list(task.get("expected_artifacts", []))


GENERIC_ARTIFACT_SCOPES = frozenset({"implementation artifact", "planning artifact"})


def path_in_write_scope(path: str, scope: list[str], *, kind: str | None = None) -> bool:
    """Match a concrete path against task write_scope, including generic artifact placeholders."""
    normalized_path = _normalize_path(path)
    if not normalized_path or ".." in normalized_path:
        return False
    resolved_kind = kind or "implementation"
    for item in scope:
        normalized_scope = _normalize_path(str(item))
        if not normalized_scope:
            continue
        if normalized_scope in GENERIC_ARTIFACT_SCOPES:
            if (
                normalized_scope == "implementation artifact"
                and _implementation_artifact_path_allowed(normalized_path, resolved_kind)
            ):
                return True
            if normalized_scope == "planning artifact" and _planning_artifact_path_allowed(
                normalized_path
            ):
                return True
            continue
        if normalized_scope.endswith("/"):
            prefix = normalized_scope.rstrip("/")
            if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
                return True
            continue
        if normalized_path == normalized_scope or normalized_path.startswith(
            normalized_scope + "/"
        ):
            return True
    return False


def _implementation_artifact_path_allowed(path: str, kind: str) -> bool:
    if kind not in {"implementation", "report", "ui", "verification", "diagnostic"}:
        return False
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False
    if parts[0] in {".git", "secrets"} or parts[0].startswith(".env"):
        return False
    if parts[0] in {"src", "tests", "docs", "generated", "studio"}:
        return True
    if len(parts) == 1 and parts[0].endswith(
        (".py", ".md", ".txt", ".json", ".tsx", ".ts", ".jsx", ".js", ".html", ".css", ".htm")
    ):
        return True
    return False


def _planning_artifact_path_allowed(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False
    if parts[0] in {"docs", "benchmarks", ".asteria"}:
        return True
    return path.endswith((".md", ".json"))


def path_in_read_scope(path: str, scope: list[str], *, kind: str | None = None) -> bool:
    """Match a concrete path against task read_scope, including generic artifact placeholders."""
    normalized_path = _normalize_path(path)
    if not normalized_path or ".." in normalized_path:
        return False
    if normalized_path == "." and scope:
        return True
    resolved_kind = kind or "implementation"
    if path_in_write_scope(path, scope, kind=kind):
        return True
    for item in scope:
        normalized_scope = _normalize_path(str(item))
        if normalized_scope == "implementation artifact" and _implementation_artifact_read_allowed(
            normalized_path, resolved_kind
        ):
            return True
        if normalized_scope == "planning artifact" and _planning_artifact_path_allowed(
            normalized_path
        ):
            return True
    return False


def _implementation_artifact_read_allowed(path: str, kind: str) -> bool:
    if kind not in {"implementation", "report", "ui", "verification", "diagnostic"}:
        return False
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False
    if parts[0] in {".git", "secrets"} or parts[0].startswith(".env"):
        return False
    if parts[0] in {"src", "tests", "docs", "generated", "studio"}:
        return True
    if path in {"AGENTS.md"} or path.endswith(
        (".py", ".md", ".txt", ".json", ".tsx", ".ts", ".jsx", ".js", ".html", ".css", ".htm")
    ):
        return True
    return False


def validation_commands(task: dict) -> list[str]:
    explicit = task.get("validation_commands")
    if isinstance(explicit, list):
        return _string_list(explicit)
    policy = task.get("verification_policy")
    if isinstance(policy, dict) and isinstance(policy.get("commands"), list):
        return _string_list(policy["commands"])
    return []


def failure_policy(task: dict) -> str:
    explicit = str(task.get("failure_policy") or "").strip()
    if explicit:
        return explicit
    kind = task_kind(task)
    if kind in {"diagnostic", "research", "review"}:
        return "continue_other_branches"
    if kind == "decision":
        return "require_user_decision"
    return DEFAULT_FAILURE_POLICY


def parallel_safety(task: dict) -> str:
    explicit = str(task.get("parallel_safety") or "").strip()
    if explicit:
        return explicit
    if not write_scope(task):
        return "readonly"
    return "serial"


def context_requirements(task: dict) -> dict:
    explicit = task.get("context_requirements")
    if isinstance(explicit, dict):
        return explicit
    kind = task_kind(task)
    mount_type = {
        "diagnostic": "debug_context",
        "verification": "debug_context",
        "research": "planning_context",
        "decision": "summary_context",
        "report": "summary_context",
    }.get(kind, "coding_context")
    return {
        "mount_type": mount_type,
        "include_artifacts": kind in {"implementation", "verification", "report", "ui"},
        "include_failures": kind in {"diagnostic", "verification"},
        "include_decisions": kind in {"review", "report", "decision"},
        "include_validation": kind in {"diagnostic", "verification", "report"},
        "recent_event_count": 20,
    }


def requires_changed_artifact(task: dict) -> bool:
    return bool(completion_contract(task).get("requires_changed_artifact", False))


def allows_expected_failure(task: dict) -> bool:
    return bool(completion_contract(task).get("allows_expected_failure", False))


def check_completion_contract(
    task: dict,
    changed_files: list[str],
    verification_results: list,
    allow_verified_noop: bool = False,
    unscoped_changed_files: list[str] | None = None,
) -> TaskContractCheck:
    contract = completion_contract(task)
    expected_files = _expected_changed_files(task)
    normalized_changed = sorted(set(str(item) for item in changed_files if item))
    verification_total = len(verification_results)
    verification_passed = len(
        [result for result in verification_results if getattr(result, "ok", False)]
    )
    verified_noop_allowed = (
        allow_verified_noop
        and verification_total > 0
        and verification_passed == verification_total
        and not normalized_changed
    )
    violations: list[str] = []

    if contract.get("requires_verification") and verification_total == 0:
        violations.append("required verification was not provided")
    if verification_total and verification_passed != verification_total:
        violations.append("verification did not pass")
    if (
        contract.get("requires_changed_artifact")
        and not normalized_changed
        and not verified_noop_allowed
    ):
        violations.append("required changed artifact was not produced")
    if (
        expected_files
        and not verified_noop_allowed
        and not _changed_expected_file(expected_files, normalized_changed)
    ):
        violations.append("expected changed files were not modified: " + ", ".join(expected_files))

    return TaskContractCheck(
        ok=not violations,
        violations=violations,
        changed_files=normalized_changed,
        expected_changed_files=expected_files,
        verification_total=verification_total,
        verification_passed=verification_passed,
        unscoped_changed_files=sorted(
            set(str(item) for item in (unscoped_changed_files or []) if item)
        ),
    )


def _task_text(task: dict) -> str:
    return " ".join(
        [
            str(task.get("title") or ""),
            str(task.get("description") or ""),
            " ".join(str(item) for item in task.get("acceptance", []) if item),
            " ".join(str(item) for item in task.get("expected_artifacts", []) if item),
        ]
    ).lower()


def _expected_changed_files(task: dict) -> list[str]:
    """The entries the planner named that are actually FILES we can hold the task to.

    Structural, not a vocabulary: the old hardcoded denylist ({"implementation artifact",
    "planning artifact", "src/", "tests/"}) only recognized four exact strings, so any other prose the
    planner happened to write — the plural, a rephrasing, another language — became a "file" that
    could never be modified, and the task was judged incomplete no matter how much real work it did.
    """
    explicit = task.get("expected_changed_files")
    if not isinstance(explicit, list):
        return []
    return [str(item) for item in explicit if item and looks_like_file_path(str(item))]


def _default_read_scope(task: dict) -> list[str]:
    scope = ["AGENTS.md"]
    artifacts = _string_list(task.get("expected_artifacts", []))
    expected_changes = _expected_changed_files(task)
    for item in [*artifacts, *expected_changes]:
        if item not in scope:
            scope.append(item)
        parent = _parent_scope(item)
        if parent and parent not in scope:
            scope.append(parent)
    return scope


def _parent_scope(path: str) -> str | None:
    normalized = str(path).replace("\\", "/").strip().strip("/")
    if not normalized or normalized.endswith("/"):
        return None
    if "/" not in normalized:
        return None
    return normalized.rsplit("/", 1)[0]


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if item]


def _changed_expected_file(expected_files: list[str], changed_files: list[str]) -> bool:
    changed = {_normalize_path(item) for item in changed_files}
    for expected in expected_files:
        normalized = _normalize_path(expected)
        if normalized in changed:
            return True
        if normalized.endswith("/") and any(item.startswith(normalized) for item in changed):
            return True
    return False


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()
