# Slice S21 — Swarm Gray Gate (Maintainer)

## observed_pattern

- Phase 5 蜂群入口需要 **maintainer 灰度路径**：fake_serial + export + dry-run，不打开 `real_disjoint_write_workers`。
- 闸门 json 汇总 S18–S21 契约测试与 Studio smoke。
- Beta 默认路径不变（session_agent）。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| `swarm_gate_audit.py` | run_dir 证据链审计 | ✅ |
| `swarm_pipeline.py` | maintainer disjoint gray path | ✅ |
| `phase5_swarm_gate.json` | Phase 5 闸门契约 | ✅ |
| `swarm_maintainer_gray_check.py` | 维护者一键复验 | ✅ |

## green_checks

```bash
python scripts/swarm_maintainer_gray_check.py --root . --skip-studio
pytest tests/integration/test_phase5_swarm_gate.py -q
python scripts/swarm_maintainer_gray_check.py --root .
```

## 退出条件

- gray path audit 绿
- phase5_swarm_gate.json  wired
- Phase 5 entry signoff
