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
