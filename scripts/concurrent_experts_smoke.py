"""并发专家真机 smoke(ADR-0023 B1-a/B1-b · 真 glm/minimax)。

大重塑 Part B B1 的**真栈复验**:B1-a 只读扇出 + B1-b 隔离写此前只由 `Barrier(2)`
确定性 fake 证过(证 ThreadPool 真并发),**从未在真弱模型栈上跑通**。本脚本忠实驱动
**完整 `ExecuteCommand` 生产路径**(经 `_SubagentAwareToolRunner` + 真并发批派发 +
merge_gate),验证真 glm/minimax 的 lead 会不会**自发**在一批里发 ≥2 个 spawn_subagent、
并发管线端到端产出正确证据。planning 用确定性桩(只搭脚手架),**execution 用真模型**。

并发信号(真栈无法塞 Barrier):两条 dispatch 卡都先于两条 result 卡 = 并发批(ThreadPool);
dispatch→result→dispatch→result = 串行回退。诚实优先:真模型若不扇出,如实报告(弱模型
可能需更强脚手架),不假成功。

用法:python scripts/concurrent_experts_smoke.py [--mode readonly|disjoint|conflict] [--tier strong|medium]
  - conflict:两个写专家写**同一路径**,验合并门挡下冲突 + 共享工作区零污染(B1-b 冲突分支真栈补验)。
⚠️ 在 worktree 里跑须 `PYTHONPATH=<worktree>/src`(editable 安装指向主副本·否则测错代码)。
需环境有 AGENT_MODEL_API_KEY / AGENT_MODEL_STRONG_API_KEY。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

_ROOT = Path(__file__).resolve().parents[1]

# Windows 控制台默认 GBK,中文 narration 会 UnicodeEncodeError —— 强制 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")


class SeedGoalClient:
    """确定性 goal 桩:只给 PlanCommand 搭一个合法 goal_spec 脚手架(execution 用真模型)。"""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "delegate a parallel expert task",
                    "normalized_goal": "Delegate a parallel expert task",
                    "goal_type": "software_tool",
                    "assumptions": ["local files are acceptable"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Delegate two independent sub-tasks to experts",
                            "source": "inferred",
                            "acceptance": ["both sub-tasks handled"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["both sub-tasks handled"],
                    "verification_strategy": ["run a command"],
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


def _readonly_task() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "task_id": "task-0001",
        "title": "并行评审两个说明文件",
        "description": (
            "工作区有两个待评审文件:notes/alpha.md 和 notes/beta.md。"
            "请在**同一步**里发出**两个 spawn_subagent 调用**(role=reviewer),"
            "把 alpha.md 交给第一个 reviewer 专家、beta.md 交给第二个 reviewer 专家并行评审"
            "(在一个 tool_calls 数组里同时给出两个 spawn_subagent)。"
            "拿到两位专家的摘要后,用 write_file 把合并结论写到 notes/review_summary.md,然后收尾。"
        ),
        "status": "pending",
        "priority": "must",
        "role": "generalist",
        "depends_on": [],
        "acceptance": ["两个 reviewer 专家各评审一个文件", "合并结论已写入 notes/review_summary.md"],
        "allowed_tools": ["read_file", "write_file", "run_command", "spawn_subagent"],
        "expected_artifacts": ["notes/review_summary.md"],
        "read_scope": ["notes/alpha.md", "notes/beta.md"],
        "write_scope": ["notes/review_summary.md"],
    }


def _disjoint_task() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "task_id": "task-0001",
        "title": "并行实现两个独立模块",
        "description": (
            "请在**同一步**里发出**两个 spawn_subagent 调用**(role=coder)并行实现两个互不相干的模块:"
            "第一个 coder 专家写 src/alpha.py(含 def alpha(): return 'A'),write_scope=['src/alpha.py'];"
            "第二个 coder 专家写 src/beta.py(含 def beta(): return 'B'),write_scope=['src/beta.py']"
            "(在一个 tool_calls 数组里同时给出两个 spawn_subagent,各自声明自己的 write_scope)。"
            "两位专家完成后,用 run_command 运行 "
            "`python -c \"import sys; sys.path.insert(0,'src'); import alpha,beta; print(alpha.alpha(),beta.beta())\"` "
            "验证两个文件都已并入工作区,然后收尾。"
        ),
        "status": "pending",
        "priority": "must",
        "role": "generalist",
        "depends_on": [],
        "acceptance": ["src/alpha.py 与 src/beta.py 均已产出并可导入"],
        "allowed_tools": ["read_file", "write_file", "run_command", "spawn_subagent"],
        "expected_artifacts": ["src/alpha.py", "src/beta.py"],
        "read_scope": [],
        # lead 本身不直接写(写委派给两个 coder 子专家各自声明 write_scope),故自身 write_scope 空。
        # delegation-brief 质量 gate 曾对此误挡(缺 allowed_writes),已修:委派型 lead(spawn_subagent
        # 且无自身 write_scope)不再要求 allowed_writes(worker_recorder.delegation_brief.delegates_writes)。
        "write_scope": [],
    }


def _conflict_task() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "task_id": "task-0001",
        "title": "并发写冲突(预期被合并门挡下)",
        "description": (
            "请在**同一步**里发出**两个 spawn_subagent 调用**(role=coder),两位专家**都写同一个文件** "
            "src/shared.py(第一个写 `def shared(): return 'A'`、write_scope=['src/shared.py'];"
            "第二个写 `def shared(): return 'B'`、write_scope=['src/shared.py'])"
            "(在一个 tool_calls 数组里同时给出两个 spawn_subagent,各自声明 write_scope=['src/shared.py'])。"
            "这是**故意的写冲突**——合并门应当挡下、共享工作区不落任何东西。拿到两位专家结果后,"
            "用一句话中文说明冲突已被合并门挡下,然后收尾(不要再写 src/shared.py)。"
        ),
        "status": "pending",
        "priority": "must",
        "role": "generalist",
        "depends_on": [],
        "acceptance": ["两个 coder 都试图写 src/shared.py", "合并门挡下冲突、工作区无 src/shared.py"],
        "allowed_tools": ["read_file", "write_file", "run_command", "spawn_subagent"],
        # 预期产物为空:冲突被挡下、什么都不该落盘,故不设 expected_artifacts(否则续跑守门会
        # 等一个合并门本就该挡住的文件)。lead 委派写、自身 write_scope 空(delegates_writes 过 brief 门)。
        "expected_artifacts": [],
        "read_scope": [],
        "write_scope": [],
    }


def _seed_workspace(ws: Path, mode: str) -> None:
    InitCommand(ws).run()
    policy_path = ws / ".asteria" / "policies.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    agent_loop = policy.setdefault("agent_loop", {})
    agent_loop["model_driven_turn"] = True
    agent_loop["concurrent_subagents"] = True
    if mode in {"disjoint", "conflict"}:
        agent_loop["isolated_parallel_write_production_path"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    if mode == "readonly":
        notes = ws / "notes"
        notes.mkdir(exist_ok=True)
        (notes / "alpha.md").write_text("# Alpha\n本模块负责 A。\n", encoding="utf-8")
        (notes / "beta.md").write_text("# Beta\n本模块负责 B。\n", encoding="utf-8")


def _analyze(run_dir: Path, mode: str) -> dict[str, Any]:
    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    subagent_cards = [
        e
        for e in events
        if e.get("transcript_kind") == "subagent_summary"
        and e.get("display_level") == "main"
    ]
    dispatch = [e for e in subagent_cards if (e.get("data") or {}).get("subagent_phase") == "dispatch"]
    result = [e for e in subagent_cards if (e.get("data") or {}).get("subagent_phase") == "result"]
    child_ids = sorted({(e.get("data") or {}).get("child_task_id") for e in result if (e.get("data") or {}).get("child_task_id")})
    roles = sorted({(e.get("data") or {}).get("subagent_role") for e in result})
    # 并发信号:两 dispatch 卡都在两 result 卡之前(ThreadPool 批) vs 交错(串行)。
    order = [
        ((e.get("data") or {}).get("subagent_phase"))
        for e in subagent_cards
    ]
    concurrent_batch = False
    if len(dispatch) >= 2 and len(result) >= 2:
        first_two = order[:2]
        concurrent_batch = first_two == ["dispatch", "dispatch"]
    # merge_gate 证据(disjoint/conflict 模式)。ok=False 即合并门挡下(disjoint 违规或跨任务写冲突)。
    merge_gate = []
    merge_path = run_dir / "merge_gate_dry_runs.jsonl"
    if merge_path.exists():
        merge_gate = [
            json.loads(line)
            for line in merge_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    merge_gate_blocked = any(record.get("ok") is False for record in merge_gate)
    merge_gate_ok = any(record.get("ok") is True for record in merge_gate)
    distinct_event_ids = len({e.get("event_id") for e in events}) == len(events)
    return {
        "dispatch_count": len(dispatch),
        "result_count": len(result),
        "child_ids": child_ids,
        "roles": roles,
        "concurrent_batch": concurrent_batch,
        "merge_gate_runs": len(merge_gate),
        "merge_gate_blocked": merge_gate_blocked,
        "merge_gate_ok": merge_gate_ok,
        "distinct_event_ids": distinct_event_ids,
        "card_order": order,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["readonly", "disjoint", "conflict"], default="readonly")
    parser.add_argument("--tier", choices=["strong", "medium"], default="strong")
    parser.add_argument("--keep", action="store_true", help="保留临时工作区便于事后查证")
    args = parser.parse_args()

    from asteria_runtime.models.factory import create_model_client
    from asteria_runtime.storage.schema_validator import SchemaValidator

    ws = Path(tempfile.mkdtemp(prefix=f"concurrent_experts_{args.mode}_"))
    print(f"=== 并发专家真机 smoke 开始 (mode={args.mode}, tier={args.tier}, ws={ws}) ===")
    try:
        _seed_workspace(ws, args.mode)
        plan = PlanCommand(ws, "delegate a parallel expert task", model_client=SeedGoalClient()).run()
        run_dir = ws / ".asteria" / "runs" / plan.run_id
        # 覆盖 planner 的 task_plan,播种一个明确指示并行委派的单任务(受验的是执行层并发机制)。
        task = {
            "readonly": _readonly_task,
            "disjoint": _disjoint_task,
            "conflict": _conflict_task,
        }[args.mode]()
        (run_dir / "task_plan.json").write_text(
            json.dumps({"schema_version": "0.1.0", "tasks": [task]}, ensure_ascii=False),
            encoding="utf-8",
        )

        model = create_model_client(None, SchemaValidator(_ROOT / "schemas"))
        # execution_model_tier 通过 context_overrides 传:medium=minimax、strong=glm。
        overrides = {"execution_model_tier": args.tier}
        ExecuteCommand(
            ws, run_id=plan.run_id, model_client=model, context_overrides=overrides
        ).run()

        report = _analyze(run_dir, args.mode)
        print("\n--- 证据分析 ---")
        for key, value in report.items():
            print(f"  {key}: {value}")

        # 独立核验产物。
        print("\n--- 产物核验 ---")
        shared_exists = (ws / "src" / "shared.py").exists()
        if args.mode == "readonly":
            summary = run_dir_root_file(ws, "notes/review_summary.md")
            print(f"  notes/review_summary.md 存在={summary is not None}")
        elif args.mode == "disjoint":
            for rel in ("src/alpha.py", "src/beta.py"):
                print(f"  {rel} 存在={(ws / rel).exists()}")
        else:  # conflict:两写专家写同一路径,合并门应挡下 → 共享工作区不该有 src/shared.py
            print(f"  src/shared.py 存在={shared_exists}(预期 False=零污染)")

        fanned_out = report["dispatch_count"] >= 2 and report["result_count"] >= 2
        if args.mode == "conflict":
            # conflict 的 PASS = 扇出 + 合并门挡下(ok=False) + 共享工作区零污染(shared.py 不存在)。
            conflict_ok = fanned_out and report["merge_gate_blocked"] and not shared_exists
            verdict = "PASS" if conflict_ok else (
                "NO-FANOUT(真模型未自发扇出·如实报告)" if not fanned_out else "FAIL(合并门未挡下或有污染)"
            )
        else:
            verdict = "PASS" if fanned_out else "NO-FANOUT(真模型未自发扇出·如实报告)"
        print(f"\n=== SMOKE {verdict} ===")
        if fanned_out:
            print(
                f"  并发批={report['concurrent_batch']} · 专家 role={report['roles']} · "
                f"distinct child={len(report['child_ids'])} · event_id 无撞={report['distinct_event_ids']}"
            )
            if args.mode == "disjoint":
                print(f"  merge_gate 汇合运行={report['merge_gate_runs']} · ok={report['merge_gate_ok']}")
            if args.mode == "conflict":
                print(
                    f"  merge_gate 运行={report['merge_gate_runs']} · 挡下(ok=False)="
                    f"{report['merge_gate_blocked']} · 共享区 shared.py={shared_exists}"
                )
        return 0
    finally:
        if args.keep:
            print(f"\n(保留工作区: {ws})")
        else:
            shutil.rmtree(ws, ignore_errors=True)


def run_dir_root_file(ws: Path, rel: str) -> Path | None:
    path = ws / rel
    return path if path.exists() else None


if __name__ == "__main__":
    raise SystemExit(main())
