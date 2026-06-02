# Alpha.2 下一批 scoped dogfooding 报告

更新时间：2026-06-02

本文记录 `alpha2-next-scoped-dogfooding` 三个任务的执行结果，用作 final report、ops-signal 和 evidence bundle 的人工可读入口。

## 批次范围

- `real_repair_task`：修复当前状态文档中 ContextBudgetMeter v2 仍被描述为“待完成”的过时冲突。
- `multi_file_small_feature`：增强 `ops-signal --analyze`，让 next batch completed evidence 同时包含显式证据路径和 `run:<id>` 引用；同步测试与命令文档。
- `context_pressure_maintenance`：用真实文档与源码切片验证 ContextBudgetMeter v2 的 before/after、恢复摘要、文件 hash/diff 和噪声归因可读性。

## 结果

### real_repair_task

状态：accepted

修复内容：

- `docs/zh/当前状态与路线.md` 的 ContextBudgetMeter v2 段落已从“仍需要文件级 hash/diff、compact before/after、恢复摘要”更新为“已具备”，并把剩余工作收敛为真实 context-heavy task 的可读性验证和 Inspector 展示。

验证证据：

- `pytest tests/unit/test_ops_signal_command.py tests/unit/test_documentation_contracts.py tests/unit/test_context_budget.py -q --tb=short`：25 passed。

### multi_file_small_feature

状态：accepted

变更内容：

- `src/asteria_runtime/core/usage_signal.py`：next batch completed 状态的 `evidence_refs` 现在追加对应 `run:<id>`。
- `tests/unit/test_ops_signal_command.py`：新增断言覆盖 completed evidence 中的三个 run refs。
- `docs/zh/运行命令.md`：记录 completed next batch evidence 会保留显式路径和 run refs。

验证证据：

- `pytest tests/unit/test_ops_signal_command.py tests/unit/test_documentation_contracts.py tests/unit/test_context_budget.py -q --tb=short`：25 passed。
- `ruff check src/asteria_runtime/core/usage_signal.py tests/unit/test_ops_signal_command.py`：passed。

### context_pressure_maintenance

状态：accepted

维护检查输入：

- `docs/zh/当前状态与路线.md`
- `docs/zh/代码现状差距与研发计划.md`
- `docs/zh/运行命令.md`
- `src/asteria_runtime/core/context_budget.py`
- `src/asteria_runtime/core/usage_signal.py`

ContextBudgetMeter v2 读数：

```json
{
  "pressure_status": "hard_stop",
  "estimated_tokens": 21282,
  "compact_boundary": {
    "status": "required",
    "recommended_action": "compact_before_next_child_round",
    "estimated_tokens_before": 21282,
    "estimated_tokens_after": 85,
    "estimated_tokens_delta": 21197,
    "estimated_duplicate_tokens": 0,
    "preserve_sections": [
      "goal_brief",
      "task_brief",
      "failures",
      "validations"
    ],
    "droppable_sections": [
      "read_scope_files"
    ]
  },
  "recovery_summary": {
    "available": true,
    "sections": [
      "failures",
      "validations"
    ],
    "evidence_refs": [
      ".asteria/context-maintenance/context-envelope.json"
    ]
  },
  "file_context": {
    "file_ref_count": 5,
    "hash_ref_count": 5,
    "diff_ref_count": 3,
    "changed_ref_count": 3
  },
  "largest_section": "read_scope_files"
}
```

判断：

- before/after/delta 能解释 compact 收益。
- recovery summary 能说明保留失败与验证信息，不暴露原始上下文正文。
- file context 能区分 unchanged、modified、hash refs 和 diff refs。
- largest section 指向 `read_scope_files`，符合 context-heavy maintenance 的直觉。

## 后续判断

本批次可以写入 accepted ops-signal。批次结束后应重新运行：

```powershell
python -m asteria_runtime ops-signal --root H:\mult_agent_code --summary --analyze --json
python -m asteria_runtime evidence-bundle --root H:\mult_agent_code --max-runs 8 --json
```

当前批次结束状态：

- `ops-signal --summary --analyze`：`next_batch_plan.status=completed`，三类 task 均有 accepted evidence。
- alpha2-next fresh evidence bundle：`.asteria/evidence_bundles/evidence-2026-06-02T234335-0800.zip`。
- route guidance refresh 后 fresh evidence bundle：`.asteria/evidence_bundles/evidence-2026-06-03T003702-0800.zip`。
- `gate-status --json`：`release_ready=true`，`route_guidance.status=healthy`，`runtime_readiness_gate.status=ready`，`blocked=0`，`review=0`，`ready=10`。
- `capability-report`：`Route guidance: healthy`。

决策：

- route guidance refresh 已完成并写入 `usage-signal-0011`；下一阶段进入受控真实 provider 小任务滚动验证。
- 不进入真实 disjoint write workers 灰度；该 feature flag 继续默认关闭，直到 route、promotion/recovery 和 rollback 风险都有更多真实样本。
