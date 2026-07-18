"""S90 对话/上下文管理三刀的单测：真尺子（per-model 窗口 + 真 usage 校准）、
grounding 瘦身（slim_workspace_files）、hard-stop 有界自动回收（_budget_guard）。"""

from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.context_budget import (
    context_pressure,
    context_window_config_miss,
    resolve_context_window,
    slim_workspace_files,
)


def _policy(**context: object) -> dict:
    return {"context": context}


# ---------- 刀二：per-model / per-provider 窗口 ----------


def test_resolve_context_window_prefers_model_then_provider_then_default() -> None:
    policy = _policy(
        model_context_window_tokens=200_000,
        model_context_windows={"glm-5": 128_000, "zhipu": 130_000},
    )

    assert resolve_context_window(policy, model_name="glm-5", provider="zhipu") == 128_000
    assert resolve_context_window(policy, model_name="unknown", provider="zhipu") == 130_000
    assert resolve_context_window(policy, model_name="unknown", provider="other") == 200_000
    assert resolve_context_window({}, model_name="glm-5") == 200_000


def test_context_pressure_uses_per_model_window() -> None:
    policy = _policy(
        model_context_window_tokens=200_000,
        model_context_windows={"glm-5": 100_000},
        compaction_threshold=0.75,
        hard_stop_threshold=0.9,
    )

    # 80k tokens：对全局 200k 是 0.4（within），对 glm-5 的真窗口 100k 是 0.8（near_limit）。
    global_view = context_pressure(policy, 80_000)
    model_view = context_pressure(policy, 80_000, model_name="glm-5")

    assert global_view.status == "within_budget"
    assert model_view.status == "near_limit"
    assert model_view.window_tokens == 100_000


# ---------- 刀二：真 usage 校准与压力真值 ----------


def test_observed_usage_becomes_pressure_of_record_and_calibrates_estimates() -> None:
    controller = BudgetController(
        _policy(
            model_context_window_tokens=10_000, compaction_threshold=0.75, hard_stop_threshold=0.9
        )
    )

    controller.record_context_estimate(1_000)
    assert controller.usage.latest_context_estimated_tokens == 1_000

    # provider 真报 2000：真值覆盖记录，校准因子向 observed/estimated=2.0 走一半（EMA α=0.5）。
    controller.record_context_observation(2_000)
    assert controller.usage.latest_observed_prompt_tokens == 2_000
    assert controller.usage.latest_context_estimated_tokens == 2_000
    assert controller.usage.context_estimate_calibration == 1.5

    # 下一次同样的原始估算 1000 → 校准后 1500 进压力计算。
    controller.record_context_estimate(1_000)
    assert controller.usage.latest_context_estimated_tokens == 1_500


def test_calibration_is_clamped_against_pathological_usage_reports() -> None:
    controller = BudgetController(_policy(model_context_window_tokens=10_000))

    controller.record_context_estimate(1_000)
    controller.record_context_observation(1_000_000)  # 疯狂值：observed/estimated=1000 → 钳到 4

    assert controller.usage.context_estimate_calibration == 0.5 * 1.0 + 0.5 * 4.0


def test_new_context_fields_round_trip_through_cost_report() -> None:
    controller = BudgetController(_policy(model_context_window_tokens=10_000))
    controller.record_context_estimate(1_000)
    controller.record_context_observation(2_000)

    report = controller.cost_report()
    assert report["latest_observed_prompt_tokens"] == 2_000
    assert report["context_estimate_calibration"] == 1.5

    revived = BudgetController.from_report(_policy(model_context_window_tokens=10_000), report)
    assert revived.usage.latest_observed_prompt_tokens == 2_000
    assert revived.usage.context_estimate_calibration == 1.5


# ---------- 刀三：grounding 瘦身 ----------


def test_slim_workspace_files_keeps_inventory_drops_content() -> None:
    slimmed = slim_workspace_files(
        [
            {"path": "app.py", "content": "SECRET_EXCERPT = 1\n" * 50},
            {"path": "notes.md", "content": "# big\n" * 100},
            "not-a-dict",
        ]
    )

    assert [item["path"] for item in slimmed] == ["app.py", "notes.md"]
    assert all("content" not in item for item in slimmed)
    assert all("read_file" in item["content_elided_under_context_pressure"] for item in slimmed)


# ---------- 刀三：hard-stop 有界自动回收（_budget_guard） ----------


class _FakeCompact:
    calls: list[str] = []

    def __init__(self, root: Path, run_id: str | None = None, focus: str = "") -> None:
        self.focus = focus

    def run(self):  # noqa: ANN201 - mirrors CompactResult surface the guard reads
        _FakeCompact.calls.append(self.focus)

        class _Result:
            snapshot_path = Path("context-snapshot-fake.json")

        return _Result()


def _guard(tmp_path: Path, monkeypatch, report: dict) -> tuple[bool, list, list[str]]:
    InitCommand(tmp_path).run()
    command = RunCommand(tmp_path, "goal")
    _FakeCompact.calls = []
    paused: list[str] = []
    monkeypatch.setattr("asteria_runtime.commands.run_command.CompactCommand", _FakeCompact)
    monkeypatch.setattr(RunCommand, "_cost_report", lambda self, run_id: report)
    monkeypatch.setattr(RunCommand, "_pending_budget_decision", lambda self, run_id: False)
    monkeypatch.setattr(
        RunCommand,
        "_create_budget_decision",
        lambda self, run_id, pressure, phase: {"decision_id": "decision-test"},
    )
    monkeypatch.setattr(
        RunCommand,
        "_pause_run_for_budget",
        lambda self, run_id, reason: paused.append(reason),
    )
    steps: list = []
    stopped = command._budget_guard("run-test", steps, "execute")
    return stopped, steps, paused


def _report(context_ratio: float, compactions: int, model_calls: int = 0) -> dict:
    return {
        "model_calls": model_calls,
        "tool_calls": 0,
        "repair_attempts": 0,
        "research_calls": 0,
        "user_decisions": 0,
        "context_compactions": compactions,
        "context_window_ratio": context_ratio,
    }


def test_context_hard_stop_auto_compacts_and_continues(tmp_path: Path, monkeypatch) -> None:
    stopped, steps, paused = _guard(tmp_path, monkeypatch, _report(0.95, compactions=0))

    assert stopped is False
    assert paused == []
    assert _FakeCompact.calls and "hard-stop context recovery" in _FakeCompact.calls[0]
    assert any(step.name == "compact" for step in steps)


def test_context_hard_stop_pauses_after_bounded_recoveries(tmp_path: Path, monkeypatch) -> None:
    stopped, steps, paused = _guard(tmp_path, monkeypatch, _report(0.95, compactions=2))

    assert stopped is True
    assert paused, "第三次仍 hard_stop 必须回到人审保底"
    assert _FakeCompact.calls == []


def test_non_context_hard_stop_still_pauses_immediately(tmp_path: Path, monkeypatch) -> None:
    # model_calls 轴打满没有"瘦身"可言——自动回收只对 context_window 轴放行。
    report = _report(0.1, compactions=0, model_calls=200)

    stopped, steps, paused = _guard(tmp_path, monkeypatch, report)

    assert stopped is True
    assert paused
    assert _FakeCompact.calls == []


# ---------- 1.2.131 修 B：回显名备选键 + 配置 miss 告警 ----------


def test_resolve_context_window_matches_server_echoed_alias() -> None:
    # Operators key windows by the log-visible echoed name ("glm-5.2") while resolution runs on
    # the env-configured name ("glm-5") — the echo rides along as an alias so both keys work.
    policy = _policy(model_context_windows={"glm-5.2": 16_000})

    assert resolve_context_window(policy, model_name="glm-5", model_aliases=("glm-5.2",)) == 16_000
    assert (
        context_window_config_miss(policy, model_name="glm-5", model_aliases=("glm-5.2",)) is False
    )
    assert context_window_config_miss(policy, model_name="glm-5", provider="zai") is True
    # No config / no model info → not a miss (nothing to warn about).
    assert context_window_config_miss(_policy(), model_name="glm-5") is False
    assert context_window_config_miss(policy) is False


def test_budget_warns_once_on_window_config_miss() -> None:
    policy = {
        "budgets": {"max_model_calls_per_goal": 10},
        "context": {"model_context_windows": {"glm-5.2": 16_000}},
    }
    budget = BudgetController(policy, run_id="run-warn")

    budget.record_context_estimate(1_000, model_name="glm-5", provider="zai")
    budget.record_context_estimate(1_100, model_name="glm-5", provider="zai")

    misses = [w for w in budget.usage.warnings if "model_context_windows matched nothing" in w]
    assert len(misses) == 1
    # A matching alias silences the warning path entirely on a fresh controller.
    clean = BudgetController(policy, run_id="run-clean")
    clean.record_context_estimate(1_000, model_name="glm-5", model_aliases=("glm-5.2",))
    assert not any("matched nothing" in w for w in clean.usage.warnings)
    assert clean.usage.context_window_tokens == 16_000
