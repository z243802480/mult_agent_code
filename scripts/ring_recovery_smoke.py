"""自主环真栈 ring-recovery benchmark(S77 P1「真 benchmark 证明」· 真 glm/minimax)。

证的是**诊断+修复一个客观损坏的基线**(buggy `add` 返回 `a-b` + 1 failing test):引擎能
不能在**无人干预**下把一个**已经红的**项目自主修绿。区别于 [[flywheel-first-ignition-proven]]
(绿地创建·happy-path 一遍写对)——这是价值主张本身:执行层 auto_repair 环在无人门下自主
迭代恢复。

架构校正(ADR-0016):model-driven 世界里没有离散 repair-dispatch 计数器
(`budget.record_repair_attempt` intentionally unwired·`budget.repair_attempts` 恒 0)。"环 fire"
= 运行时在无人门下允许模型在有界 loop 内继续跑,自己「跑失败校验→见红→改→重跑→见绿→done」。
故证据契约不是 `repair_attempts>=1`,而是:基线独立验证红 → 自主 run 后独立验证绿 →
transcript 里失败校验后接通过校验(loop 内红转绿)→ 真 provider(非罐头)→ status/exit_reason
completed。诚实三态:PASS / NO-RECOVER(基线红但终仍红)/ NO-REAL-PROVIDER(跑了 fake)。

用法:python scripts/ring_recovery_smoke.py [--tier strong|medium] [--allow-fake] [--keep]
                                          [--summary-json PATH]
需环境有 AGENT_MODEL_STRONG_API_KEY(glm)/ AGENT_MODEL_API_KEY(minimax);--allow-fake 仅测管道。
⚠️ 在 worktree 里跑须 PYTHONPATH=<worktree>/src。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "benchmarks" / "failing_tests_project" / "fixtures"

# Windows 控制台默认 GBK,中文 narration 会 UnicodeEncodeError —— 强制 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")

VERIFICATION_TOOLS = {"run_tests", "run_command"}
OFFLINE_PROVIDERS = {"fake", "offline", "benchmark"}


class SeedGoalClient:
    """确定性 goal 桩:只给 PlanCommand 搭一个合法 goal_spec 脚手架(execution 用真模型)。"""

    def chat(self, request: Any) -> Any:
        from asteria_runtime.models.base import ChatResponse, TokenUsage

        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "fix the failing tests",
                    "normalized_goal": "Fix the failing tests in this project",
                    "goal_type": "software_tool",
                    "assumptions": ["local files are acceptable"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Make the project's pytest suite pass",
                            "source": "inferred",
                            "acceptance": ["pytest passes"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["pytest passes"],
                    "verification_strategy": ["run pytest"],
                    "budget": {"max_iterations": 10, "max_model_calls": 80},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="seed-goal",
            raw_response={},
        )


def _repair_task() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "task_id": "task-0001",
        "title": "修复失败的测试",
        "description": (
            "工作区里 buggy_math.py 的 add 实现有 bug(返回 a-b),tests/test_buggy_math.py "
            "断言 add(2,3)==5,当前**失败**。请先用 run_command 运行 "
            "`python -m pytest tests -q` 看到失败,修好 buggy_math.py 里的 add 使断言通过,"
            "再运行一次 `python -m pytest tests -q` 确认通过,然后收尾。只改 buggy_math.py,不要改测试。"
        ),
        "status": "pending",
        "priority": "must",
        "role": "coder",
        "depends_on": [],
        "acceptance": ["python -m pytest tests 通过", "只修改 buggy_math.py 不改测试"],
        "allowed_tools": ["read_file", "write_file", "edit_file", "run_command"],
        "expected_artifacts": ["buggy_math.py"],
        "read_scope": ["buggy_math.py", "tests/test_buggy_math.py"],
        "write_scope": ["buggy_math.py"],
    }


def _seed_workspace(ws: Path) -> None:
    from asteria_runtime.commands.init_command import InitCommand

    InitCommand(ws).run()
    policy_path = ws / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    agent_loop = policy.setdefault("agent_loop", {})
    agent_loop["model_driven_turn"] = True
    # 无人门(unsupervised):显式打开 repair/replan 环。ExecuteCommand-direct 不像 RunCommand 那样
    # 把 permission_level 接进 policy["permission_mode"],故默认绑定(autonomy_rings_default_on)在此
    # 路径不生效(会解析成 rings off);要真 unsupervised 必须显式设 flag(默认绑定另由单测覆盖)。
    agent_loop["auto_repair"] = True
    agent_loop["auto_replan"] = True
    policy["permission_mode"] = "reviewed_auto"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    # 拷已签入的损坏基线 fixture:buggy_math.py(add 返 a-b)+ tests/test_buggy_math.py(断言 ==5)。
    (ws / "buggy_math.py").write_text(
        (_FIXTURES / "buggy_math.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    tests_dir = ws / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_buggy_math.py").write_text(
        (_FIXTURES / "test_buggy_math.py").read_text(encoding="utf-8"), encoding="utf-8"
    )


def _pytest_green(ws: Path) -> bool:
    """独立核验:在 workspace 里真跑 pytest,返回是否全绿(不信 harness 自述)。"""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=str(ws),
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate_ring_recovery(
    run_dir: Path,
    *,
    baseline_red: bool,
    final_green: bool,
    allow_fake: bool,
) -> dict[str, Any]:
    """纯函数:读 run_dir 工件 + 独立 pytest 结果,按 brief 证据契约裁决。可单测(喂合成 fixture)。

    三态:PASS / NO-RECOVER(基线红但终仍红)/ NO-REAL-PROVIDER(跑了 fake·非 allow_fake)。
    另返 evidence 供人读(loop 内红转绿 / status / exit_reason / provider / rounds)。
    """
    # agent_loop_run_summary:环收尾态。
    summary_path = run_dir / "agent_loop_run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    status = str(summary.get("status") or "")
    exit_reason = str(summary.get("exit_reason") or "")
    rounds_completed = int(summary.get("rounds_completed") or 0)

    # tool_calls:loop 内校验命令红→绿(失败的校验后接通过的校验)。
    tool_calls = _read_jsonl(run_dir / "tool_calls.jsonl")
    verif = [c for c in tool_calls if c.get("tool_name") in VERIFICATION_TOOLS]
    verif_statuses = [str(c.get("status") or "") for c in verif]
    saw_red = any(s != "success" for s in verif_statuses)
    saw_green = any(s == "success" for s in verif_statuses)
    red_then_green = False
    first_fail = next((i for i, s in enumerate(verif_statuses) if s != "success"), None)
    last_pass = next(
        (i for i in range(len(verif_statuses) - 1, -1, -1) if verif_statuses[i] == "success"),
        None,
    )
    if first_fail is not None and last_pass is not None and last_pass > first_fail:
        red_then_green = True

    # model_calls:真 provider 证据(执行 tier 非 fake/offline)。
    model_calls = _read_jsonl(run_dir / "model_calls.jsonl")
    providers = sorted({str(c.get("model_provider") or "") for c in model_calls if c.get("model_provider")})
    real_providers = [p for p in providers if p.lower() not in OFFLINE_PROVIDERS]
    used_real_provider = bool(real_providers)

    # task_execution_evidence:blocked(contract.ok=false)→done 转移(记录·辅证)。
    evidence = _read_jsonl(run_dir / "task_execution_evidence.jsonl")
    saw_blocked_rejected = any(
        str(e.get("status") or "") == "blocked"
        and (e.get("contract_check") or {}).get("ok") is False
        for e in evidence
    )
    saw_done = any(str(e.get("status") or "") == "done" for e in evidence)

    loop_completed = status == "completed" and exit_reason == "completed"

    if not (baseline_red and final_green):
        verdict = "NO-RECOVER"
    elif not (used_real_provider or allow_fake):
        verdict = "NO-REAL-PROVIDER"
    elif not loop_completed:
        verdict = "NO-RECOVER"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "baseline_red": baseline_red,
        "final_green": final_green,
        "loop_status": status,
        "loop_exit_reason": exit_reason,
        "loop_completed": loop_completed,
        "rounds_completed": rounds_completed,
        "verification_calls": len(verif),
        "saw_failing_verification": saw_red,
        "saw_passing_verification": saw_green,
        "red_then_green_in_loop": red_then_green,
        "providers_seen": providers,
        "real_providers": real_providers,
        "used_real_provider": used_real_provider,
        "blocked_rejected_then_done": saw_blocked_rejected and saw_done,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=["strong", "medium"], default="strong")
    parser.add_argument("--allow-fake", action="store_true", help="强制 fake provider·仅测管道")
    parser.add_argument("--keep", action="store_true", help="保留临时工作区便于事后查证")
    parser.add_argument("--summary-json", type=Path, default=None)
    args = parser.parse_args()

    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.commands.plan_command import PlanCommand
    from asteria_runtime.models.factory import create_model_client
    from asteria_runtime.storage.schema_validator import SchemaValidator

    if args.allow_fake:
        for tier in ("STRONG", "MEDIUM", "CHEAP"):
            os.environ[f"AGENT_MODEL_{tier}_PROVIDER"] = "fake"
        os.environ["AGENT_MODEL_PROVIDER"] = "fake"

    ws = Path(tempfile.mkdtemp(prefix="ring_recovery_"))
    print(f"=== 自主环 ring-recovery 真栈 benchmark 开始 (tier={args.tier}, ws={ws}) ===")
    try:
        _seed_workspace(ws)

        baseline_red = not _pytest_green(ws)
        print(f"--- 基线核验:pytest {'RED(如期损坏)' if baseline_red else 'GREEN(异常·基线未损坏)'} ---")

        plan = PlanCommand(ws, "fix the failing tests", model_client=SeedGoalClient()).run()
        run_dir = ws / ".asteria" / "runs" / plan.run_id
        (run_dir / "task_plan.json").write_text(
            json.dumps({"schema_version": "0.1.0", "tasks": [_repair_task()]}, ensure_ascii=False),
            encoding="utf-8",
        )

        model = create_model_client(None, SchemaValidator(_ROOT / "schemas"))
        ExecuteCommand(
            ws,
            run_id=plan.run_id,
            model_client=model,
            context_overrides={"execution_model_tier": args.tier},
        ).run()

        final_green = _pytest_green(ws)
        print(f"--- 终态核验:pytest {'GREEN(修好了)' if final_green else 'RED(仍红)'} ---")

        report = evaluate_ring_recovery(
            run_dir,
            baseline_red=baseline_red,
            final_green=final_green,
            allow_fake=args.allow_fake,
        )
        print("\n--- 证据分析 ---")
        for key, value in report.items():
            if key != "verdict":
                print(f"  {key}: {value}")

        verdict = report["verdict"]
        label = {
            "PASS": "PASS",
            "NO-RECOVER": "NO-RECOVER(基线红但终仍红·环没修好·如实报告)",
            "NO-REAL-PROVIDER": "NO-REAL-PROVIDER(跑了 fake·非真栈证明)",
        }[verdict]
        print(f"\n=== RING-RECOVERY {label} ===")

        if args.summary_json:
            args.summary_json.parent.mkdir(parents=True, exist_ok=True)
            args.summary_json.write_text(
                json.dumps({"tier": args.tier, "workspace": str(ws), **report}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"(summary: {args.summary_json})")

        return 0 if verdict == "PASS" else 1
    finally:
        if args.keep:
            print(f"\n(保留工作区: {ws})")
        else:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
