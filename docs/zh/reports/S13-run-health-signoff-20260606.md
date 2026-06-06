# S13 Run Health + S7 Clean Re-run 签字记录

**状态**：signed — Phase 4 一大步：有界 recovery + run-health gate + real provider 健康复跑  
**依赖**：S12 North Star v1；Phase 4 稳态维护 A1/A2  
**日期**：2026-06-06

## 交付（代码 + 闸门 + real run）

| 项 | 交付 |
| --- | --- |
| Recovery cycle cap | `RunCommand._execute_until_no_ready` 内层循环上限（policy 驱动） |
| user_progress 防膨胀 | `ModelProgressSink` delta 持久化上限（48/call） |
| Run health 审计 | `run_health_audit.py` + `phase4_run_health_gate.json` |
| S7 clean re-run | `.asteria/s13-clean-run-workspace` real provider E2E |

## Real provider 结果（`run-20260606-0002`）

| 指标 | S7 旧 run（技术债） | S13 clean run |
| --- | --- | --- |
| run status | blocked | **completed** |
| studio-benchmark | 1.0（签字 run） | **1.0** |
| user_progress | ~32 MB / 7841 events | **2.1 MB / 1154 events** |
| replan tasks | 436 | **2** |
| repair_attempts | 1（预算未反映循环） | **5** |

## Checklist

- [x] `pytest tests/integration/test_phase4_run_health_gate.py tests/unit/test_run_health_audit.py -q`
- [x] recovery limit 集成测试绿
- [x] legacy S7 run 作为 **负例 fixture** 触发 run-health fail
- [x] `studio-benchmark --run-id run-20260606-0002` score **1.0**
- [x] run-health audit **pass**
- [x] `evidence-bundle` → `evidence-2026-06-06T143047-0800.zip`
- [x] 产物：`greet_cli.py` 含 `--version`；`tests/test_greet_cli.py`

## 复现

```powershell
pytest tests/integration/test_phase4_run_health_gate.py tests/unit/test_run_health_audit.py -q
python -m asteria_runtime studio-benchmark --root .asteria/s13-clean-run-workspace --run-id run-20260606-0002 --json
python -m asteria_runtime evidence-bundle --root .asteria/s13-clean-run-workspace --json
```

## 下一入口

- **Phase 4 闭环**：A3 完成；可选 accept 签字 run 或继续 Phase 5 RFC 观察窗（蜂群仍 defer）
- **可选优化**：进一步压缩 model delta 持久化（当前 2MB 已过 gate）
