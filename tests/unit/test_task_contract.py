from asteria_runtime.core.task_contract import (
    allows_expected_failure,
    check_completion_contract,
    looks_like_file_path,
    context_requirements,
    failure_policy,
    parallel_safety,
    path_in_read_scope,
    path_in_write_scope,
    read_scope,
    requires_changed_artifact,
    task_kind,
    validation_commands,
    write_scope,
)


def test_task_contract_uses_explicit_task_kind_and_completion_contract() -> None:
    task = {
        "task_kind": "diagnostic",
        "completion_contract": {
            "requires_changed_artifact": False,
            "requires_verification": True,
            "allows_expected_failure": True,
        },
    }

    assert task_kind(task) == "diagnostic"
    assert allows_expected_failure(task) is True
    assert requires_changed_artifact(task) is False


def test_task_contract_infers_implementation_for_legacy_tasks() -> None:
    task = {
        "title": "Fix parser bug",
        "description": "Update parser implementation",
        "acceptance": ["parser handles input"],
        "expected_artifacts": ["parser.py"],
    }

    assert task_kind(task) == "implementation"
    assert requires_changed_artifact(task) is True
    assert allows_expected_failure(task) is False


class _Result:
    def __init__(self, ok: bool) -> None:
        self.ok = ok


def test_completion_contract_requires_verification_and_expected_file_change() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(task, ["notes_tool.py"], [_Result(True)])

    assert check.ok is False
    assert check.expected_changed_files == ["password_strength.py"]
    assert "expected changed files were not modified" in check.violations[0]


def test_completion_contract_passes_when_expected_file_is_changed_and_verified() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(task, ["password_strength.py"], [_Result(True)])

    assert check.ok is True
    assert check.summary() == "Task completion contract satisfied."


def test_completion_contract_can_allow_verified_noop_for_repair_closure() -> None:
    task = {
        "task_kind": "implementation",
        "expected_changed_files": ["password_strength.py"],
    }

    check = check_completion_contract(
        task,
        [],
        [_Result(True)],
        allow_verified_noop=True,
    )

    assert check.ok is True


def test_task_contract_exposes_runtime_scopes_and_policies() -> None:
    task = {
        "task_kind": "implementation",
        "expected_artifacts": ["src/asteria_runtime/example.py"],
        "expected_changed_files": ["src/asteria_runtime/example.py"],
        "verification_policy": {"commands": ["pytest tests/unit/test_example.py"]},
    }

    assert read_scope(task) == [
        "AGENTS.md",
        "src/asteria_runtime/example.py",
        "src/asteria_runtime",
    ]
    assert write_scope(task) == ["src/asteria_runtime/example.py"]
    assert validation_commands(task) == ["pytest tests/unit/test_example.py"]
    assert failure_policy(task) == "create_repair_task"
    assert parallel_safety(task) == "serial"
    assert context_requirements(task)["mount_type"] == "coding_context"


def test_task_contract_marks_tasks_without_write_scope_as_readonly() -> None:
    task = {
        "task_kind": "research",
        "title": "Research architecture",
        "expected_artifacts": ["docs/notes.md"],
    }

    assert write_scope(task) == []
    assert parallel_safety(task) == "readonly"
    assert failure_policy(task) == "continue_other_branches"


def test_path_in_write_scope_accepts_implementation_artifact_for_src_paths() -> None:
    scope = ["implementation artifact"]
    assert path_in_write_scope("src/notes_tool.py", scope, kind="implementation") is True
    assert path_in_write_scope("blocked/output.txt", scope, kind="implementation") is False


def test_path_in_read_scope_accepts_src_directory_for_implementation_artifact() -> None:
    scope = ["AGENTS.md", "implementation artifact"]
    assert path_in_read_scope("src", scope, kind="implementation") is True
    assert path_in_read_scope("secrets/key.txt", scope, kind="implementation") is False


def test_path_in_write_scope_accepts_root_html_for_implementation_artifact() -> None:
    scope = ["implementation artifact"]
    assert path_in_write_scope("index.html", scope, kind="ui") is True
    assert path_in_write_scope("styles.css", scope, kind="ui") is True


def test_path_in_read_scope_accepts_workspace_root_listing() -> None:
    scope = ["index.html", "styles.css"]
    assert path_in_read_scope(".", scope, kind="ui") is True


class _PassedVerification:
    ok = True


def test_prose_expected_changed_files_do_not_fail_a_task_that_did_the_work() -> None:
    """The contract used to filter expected_changed_files with a hardcoded denylist of four exact
    strings, so any other wording the planner produced — the plural, a rephrasing, another language —
    was treated as a FILE that must change. A task that wrote its code and passed verification was
    then judged "expected changed files were not modified". The planner writes these entries in free
    text; no fixed vocabulary can enumerate them, so the test must be structural."""
    for placeholder in (
        "implementation artifact",
        "implementation artifacts",  # merely the plural — used to fail
        "the new notes module",
        "更新后的文档",
    ):
        task = {
            "task_id": "task-0001",
            "task_kind": "implementation",
            "expected_changed_files": [placeholder],
        }
        check = check_completion_contract(
            task,
            changed_files=["src/notes.py"],
            verification_results=[_PassedVerification()],
        )
        assert check.ok, f"{placeholder!r} must not be treated as a file: {check.violations}"


def test_a_named_file_is_still_enforced() -> None:
    """The fix must not weaken the gate: a concrete path the planner named must really be modified."""
    task = {
        "task_id": "task-0001",
        "task_kind": "implementation",
        "expected_changed_files": ["src/notes.py"],
    }
    missed = check_completion_contract(
        task, changed_files=["src/other.py"], verification_results=[_PassedVerification()]
    )
    assert not missed.ok
    assert "expected changed files were not modified" in missed.violations[0]
    hit = check_completion_contract(
        task, changed_files=["src/notes.py"], verification_results=[_PassedVerification()]
    )
    assert hit.ok


def test_doing_nothing_is_still_not_done() -> None:
    """Prose entries stop being files — they must not become a loophole to finish with no artifact."""
    task = {
        "task_id": "task-0001",
        "task_kind": "implementation",
        "expected_changed_files": ["the new module"],
    }
    check = check_completion_contract(
        task, changed_files=[], verification_results=[_PassedVerification()]
    )
    assert not check.ok
    assert "required changed artifact was not produced" in check.violations


def test_looks_like_file_path_is_structural() -> None:
    """One predicate, shared by the stop-guardrail and the completion contract — they must agree on
    what a checkable file is, or a task can be held open for something the other side ignores."""
    assert looks_like_file_path("src/notes.py") is True
    assert looks_like_file_path("index.html") is True
    assert looks_like_file_path("src/") is False  # a directory scope is not a deliverable
    assert looks_like_file_path("implementation artifact") is False  # prose
    assert looks_like_file_path("") is False
