# Slice S19 — Candidate Export + Merge Gate Dry-Run

## observed_pattern

- 蜂群 worker 完成后需 **先导出 candidate 证据**，再 **dry-run merge gate**，最后才 promotion。
- 真实 promotion 仍走现有 `CandidateExecutionGateway.promote_changes`；S19 只补 **预览链**。
- 多 worker 批次需检测：disjoint write gate + 跨 task 文件冲突。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| `candidate_export.py` | 扫描/导出 changed_files → `candidate_exports.jsonl` | ✅ |
| `merge_gate_dry_run.py` | 批次 dry-run → `merge_gate_dry_runs.jsonl` | ✅ |
| `preview_promotion` | gateway 预览，不写主工作区 | ✅ |
| schema | `candidate_export` · `merge_gate_dry_run` | ✅ |
| 集成测试 | 双 worker disjoint 批次 dry-run 绿 | ✅ |

## focus

1. **Export 契约**：harness worker → candidate_export 含 execution_profile_id
2. **Dry-run**：`dry_run: true`；不 enqueue promotion
3. **批次仲裁**：disjoint gate + cross-task file conflict
4. 不扩 execute_command 真实 parallel（KEEP_PLACEHOLDER）

## green_checks

```bash
pytest tests/unit/test_candidate_export.py tests/unit/test_merge_gate_dry_run.py -q
pytest tests/integration/test_candidate_export_merge_dry_run.py -q
python scripts/steady_iteration_check.py --root . --skip-b6
pytest tests/unit/test_documentation_contracts.py -q
```

## 退出条件

- export + dry-run schema 验证通过
- preview_promotion 不写主工作区
- 三源 ACTIVE_SLICE=S19
- S20：Studio worker 进度 + promotion UI
