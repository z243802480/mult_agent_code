"""立真身真机 smoke：真 glm/minimax + 真实文件 IO，证明模型驱动循环端到端产出可用产物。

这是 smoke（非生产路径）：用轻量 RegistryToolRunner 直接调 registry 工具，刻意绕过
ToolExecutionGateway 的权限/证据/candidate 机器（那些各有自己的测试）。目的只有一个——
证明**真实弱模型栈（glm/minimax）能被立真身循环驱动，用原生 tool_use 产出并验证 calc.py**。
全网关灰度接入是下一步（见 docs/zh/reports/architecture-conformance-audit-core-loop.md §7）。

运行需环境里有 AGENT_MODEL_API_KEY / AGENT_MODEL_STRONG_API_KEY。
用法：python scripts/model_driven_turn_smoke.py [--tier strong|medium]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 GBK，narration/中文会 UnicodeEncodeError —— 强制 UTF-8 输出。
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

from asteria_runtime.core.model_driven_turn import TurnEvent, run_model_driven_turn
from asteria_runtime.core.policy_config import merge_policy_defaults
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.defaults import create_default_tool_registry

_ROOT = Path(__file__).resolve().parents[1]

SYSTEM_PROMPT = (
    "You are CoderAgent in a local-first autonomous development runtime.\n"
    "Available tools: write_file(path, content), read_file(path), "
    "run_command(command), run_tests(command).\n"
    "- Use write_file to create files, run_command to verify.\n"
    "- Make the smallest change that satisfies the task, then verify with run_command.\n"
    "- narration is one short sentence in the user's language (Chinese) about this step."
)

USER_PROMPT = (
    "目标：在当前工作区创建 calc.py，内含函数 add(a, b) 返回 a + b。\n"
    '然后用 run_command 运行 `python -c "import calc; print(calc.add(2, 3))"` 验证输出 5。\n'
    "完成并验证后，用一句话中文收尾，不要再调用工具。"
)


class RegistryToolRunner:
    """把模型的 tool_calls 直接派到 registry 工具（打到真实 scratch 工作区）。"""

    def __init__(self, registry, context: RuntimeContext) -> None:
        self.registry = registry
        self.context = context

    def run_tool_calls(self, calls, task, context, stop_on_failure=False, **_kw):
        results = []
        for call in calls:
            name = str(call.get("tool_name") or "")
            raw_args = call.get("args")
            args = raw_args if isinstance(raw_args, dict) else {}
            results.append(
                self.registry.call(
                    name,
                    self.context,
                    task_id=str(task.get("task_id") or ""),
                    agent_id="mdt-smoke",
                    **args,
                )
            )
        return results


def _on_event(event: TurnEvent) -> None:
    if event.kind == "narration":
        print(f"[{event.iteration}] SAY : {event.text}")
    elif event.kind == "tool_observation":
        for obs in event.observations:
            print(f"[{event.iteration}] TOOL: {obs.model_summary()}")
    elif event.kind == "final":
        print(f"[{event.iteration}] DONE: {event.text}")
    elif event.kind == "fuse":
        print(f"[{event.iteration}] FUSE: budget_exhausted")


def main() -> int:
    tier = "strong"
    if "--tier" in sys.argv:
        tier = sys.argv[sys.argv.index("--tier") + 1]

    workspace = Path(tempfile.mkdtemp(prefix="mdt_smoke_"))
    validator = SchemaValidator(_ROOT / "schemas")
    model_client = create_model_client(None, validator, None)
    registry = create_default_tool_registry()
    # 真实默认 policy（带标准 protected_paths：.env/secrets/.git 等；calc.py 不在其中可写）。
    # smoke 在临时工作区里验证，开 shell 让 run_command 能跑验证命令。
    policy = merge_policy_defaults({})
    policy.setdefault("permissions", {})["allow_shell"] = True
    context = RuntimeContext(root=workspace, run_id=None, policy=policy, validator=validator)
    runner = RegistryToolRunner(registry, context)

    task = {
        "task_id": "task-0001",
        "allowed_tools": ["write_file", "read_file", "run_command", "run_tests"],
        "write_scope": ["calc.py"],
    }

    print(f"=== 立真身真机 smoke 开始 (tier={tier}, ws={workspace}) ===")
    result = run_model_driven_turn(
        model_client=model_client,
        tool_runner=runner,
        task=task,
        context=context,
        available_tools=["write_file", "read_file", "run_command", "run_tests"],
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT,
        model_tier=tier,
        max_iterations=6,
        on_event=_on_event,
    )
    print(f"=== 循环结束: status={result.status} iterations={result.iterations} ===")

    calc = workspace / "calc.py"
    produced = calc.exists()
    verified = False
    if produced:
        proc = subprocess.run(
            [sys.executable, "-c", "import calc; print(calc.add(2, 3))"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        verified = proc.stdout.strip() == "5"
        print(f"独立核验: calc.py 存在=True, add(2,3)={proc.stdout.strip()!r}, 通过={verified}")
    else:
        print("独立核验: calc.py 未产出")

    shutil.rmtree(workspace, ignore_errors=True)
    ok = result.status == "completed" and produced and verified
    print(f"=== SMOKE {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
