from asteria_runtime.core.multi_agent_strategy import MultiAgentStrategyAdvisor


def test_strategy_keeps_single_bounded_write_serial() -> None:
    task = {
        "task_kind": "implementation",
        "acceptance": ["file exists"],
        "expected_artifacts": ["tool.py"],
        "expected_changed_files": ["tool.py"],
        "write_scope": ["tool.py"],
        "parallel_safety": "serial",
    }

    strategy = MultiAgentStrategyAdvisor().for_task(task)

    assert strategy.mode == "serial_worker"
    assert strategy.max_child_workers == 1
    assert strategy.coordination_policy["requires_merge_gate"] is True


def test_strategy_allows_readonly_fanout_for_research() -> None:
    task = {
        "task_kind": "research",
        "acceptance": ["inspect alpha", "inspect beta", "inspect gamma"],
        "expected_artifacts": [],
        "expected_changed_files": [],
        "write_scope": [],
        "parallel_safety": "readonly",
    }

    strategy = MultiAgentStrategyAdvisor().for_task(task)

    assert strategy.mode == "readonly_fanout"
    assert strategy.max_child_workers >= 3
    assert strategy.coordination_policy["write_allowed"] is False


def test_strategy_allows_disjoint_write_workers_for_independent_outputs() -> None:
    task = {
        "task_kind": "implementation",
        "acceptance": ["alpha exists", "beta exists"],
        "expected_artifacts": ["out/alpha.txt", "out/beta.txt"],
        "expected_changed_files": ["out/alpha.txt", "out/beta.txt"],
        "write_scope": ["out/alpha.txt", "out/beta.txt"],
        "parallel_safety": "disjoint_writes",
    }

    strategy = MultiAgentStrategyAdvisor().for_task(task)

    assert strategy.mode == "disjoint_write_workers"
    assert strategy.max_child_workers == 2
    assert strategy.planner_child_plan is True
    assert strategy.coordination_policy["requires_disjoint_write_scope"] is True
