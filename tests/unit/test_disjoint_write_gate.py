from asteria_runtime.core.disjoint_write_gate import DisjointWriteGate


def _task(task_id: str, write_scope: list[str], **overrides) -> dict:
    task = {
        "task_id": task_id,
        "parallel_safety": "disjoint_writes",
        "write_scope": write_scope,
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
    }
    task.update(overrides)
    return task


def _promotion(
    task_id: str,
    *,
    status: str = "promoted",
    merge_ok: bool = True,
    files: list[str] | None = None,
    candidate_id: str = "candidate-0001",
    workspace: str = "cw/0001",
    workspace_policy: str = "isolated_copy",
) -> dict:
    return {
        "promotion_id": f"promotion-{task_id}",
        "task_id": task_id,
        "candidate_id": candidate_id,
        "workspace": workspace,
        "workspace_policy": workspace_policy,
        "promotable_files": files or ["src/a.py"],
        "status": status,
        "merge_gate": {
            "ok": merge_ok,
            "violations": [] if merge_ok else ["changed files outside write_scope"],
        },
    }


def test_disjoint_write_gate_allows_verified_disjoint_write_scopes() -> None:
    result = DisjointWriteGate().evaluate(
        [
            _task("task-0001", ["src/a.py"]),
            _task("task-0002", ["src/b.py"]),
        ],
    )

    assert result.ok is True
    assert result.allowed_task_ids == ["task-0001", "task-0002"]
    assert result.blocked_task_ids == []


def test_disjoint_write_gate_allows_candidate_promotions_after_passed_merge_gates() -> None:
    result = DisjointWriteGate().evaluate(
        [
            _task("task-0001", ["src/a.py"]),
            _task("task-0002", ["src/b.py"]),
        ],
        promotions=[
            _promotion("task-0001", files=["src/a.py"]),
            _promotion("task-0002", files=["src/b.py"]),
        ],
        require_candidate_promotions=True,
    )

    assert result.ok is True
    assert result.allowed_task_ids == ["task-0001", "task-0002"]
    assert result.blocked_task_ids == []


def test_disjoint_write_gate_blocks_overlapping_write_scopes() -> None:
    result = DisjointWriteGate().evaluate(
        [
            _task("task-0001", ["src/"]),
            _task("task-0002", ["src/b.py"]),
        ],
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001", "task-0002"]
    assert result.violations == ["task-0001/task-0002: write_scope overlaps"]


def test_disjoint_write_gate_blocks_missing_verification_contract() -> None:
    result = DisjointWriteGate().evaluate(
        [
            _task(
                "task-0001",
                ["src/a.py"],
                completion_contract={"requires_changed_artifact": True},
            ),
        ],
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001"]
    assert "requires_verification" in result.violations[0]


def test_disjoint_write_gate_blocks_unresolved_promotion_recovery() -> None:
    result = DisjointWriteGate().evaluate(
        [_task("task-0001", ["src/a.py"])],
        promotions=[
            {
                "promotion_id": "promotion-0001",
                "status": "promotion_failed",
                "recovery_status": "unresolved",
            }
        ],
    )

    assert result.ok is False
    assert result.allowed_task_ids == []
    assert result.blocked_task_ids == ["task-0001"]
    assert result.violations == ["promotion recovery unresolved: promotion-0001"]


def test_disjoint_write_gate_blocks_missing_candidate_promotion_evidence() -> None:
    result = DisjointWriteGate().evaluate(
        [_task("task-0001", ["src/a.py"])],
        require_candidate_promotions=True,
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001"]
    assert result.violations == ["task-0001: candidate promotion evidence is required"]


def test_disjoint_write_gate_blocks_failed_merge_gate() -> None:
    result = DisjointWriteGate().evaluate(
        [_task("task-0001", ["src/a.py"])],
        promotions=[_promotion("task-0001", merge_ok=False)],
        require_candidate_promotions=True,
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001"]
    assert "merge gate must pass" in result.violations[0]


def test_disjoint_write_gate_blocks_promotion_files_outside_write_scope() -> None:
    result = DisjointWriteGate().evaluate(
        [_task("task-0001", ["src/a.py"])],
        promotions=[_promotion("task-0001", files=["src/b.py"])],
        require_candidate_promotions=True,
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001"]
    assert result.violations == [
        "task-0001: promotable_files outside write_scope: src/b.py"
    ]


def test_disjoint_write_gate_blocks_missing_candidate_workspace_fields() -> None:
    result = DisjointWriteGate().evaluate(
        [_task("task-0001", ["src/a.py"])],
        promotions=[
            _promotion(
                "task-0001",
                candidate_id="",
                workspace="",
                workspace_policy="",
            )
        ],
        require_candidate_promotions=True,
    )

    assert result.ok is False
    assert result.blocked_task_ids == ["task-0001"]
    assert result.violations == [
        "task-0001: candidate_id is required",
        "task-0001: candidate workspace is required",
        "task-0001: candidate workspace_policy is required",
    ]
