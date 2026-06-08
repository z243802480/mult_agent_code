# S74 Post-S73 Beta Convergence

## observed_pattern

成熟 agent 产品在新增编排能力后，先用真实任务校准主路径、延迟、恢复和用户叙事，再决定是否扩大默认权限。能力存在不等于产品路径已经可靠。

## asteria_file

- `docs/zh/研发总计划.md`
- `docs/zh/当前状态与路线.md`
- `benchmarks/vibe_slices.json`
- `tests/integration/test_execute_command.py`
- `scripts/orchestration_s73_signoff_pulse.py`
- `scripts/beta_task_pack_check.py`
- `scripts/beta_friction_aggregate.py`

## slice_goal

在不新增编排 Wave 的前提下，完成 Post-S73 收敛：

1. 统一执行真源，关闭过期 active 计划。
2. 恢复最新主路径测试基线，优先修契约漂移而非加兼容分支。
3. 让 maintainer pulse 使用 workspace-local、可复现的临时目录和解释器。
4. 跑 3–5 个真实 Beta 任务，覆盖 session agent、subagent、L3 orchestration、显式 parallel writes opt-in。
5. 记录完成率、耗时分解、model/tool calls、repair 次数、用户进展一致性。
6. 基于证据创建下一阶段 DecisionPoint：继续维护、扩大 opt-in，或回退复杂能力。

## do_not_copy

- 不因能力已实现就默认开启 parallel writes。
- 不为单个失败任务增加 domain keyword 分支。
- 不把 maintainer gate、route 或内部 evidence 搬到 Studio 主会话。
- 不在基线未恢复前新增 Wave 9 或新的编排层。

## green_checks

```powershell
pytest tests/unit/test_documentation_contracts.py -q
pytest tests/integration/test_execute_command.py -q
python scripts/orchestration_s73_signoff_pulse.py --root .
python scripts/beta_task_pack_check.py --root .
python scripts/beta_friction_aggregate.py --root .
python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel
```
