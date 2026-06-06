# Phase 4 稳态维护签字记录

**状态**：signed — 轨道 A1/A2 常规验证全绿  
**前提**：S12 North Star v1 已签字（[`S12-north-star-signoff-20260606.md`](./S12-north-star-signoff-20260606.md)）  
**日期**：2026-06-06

## 范围（务实路径）

不启动 Phase 5 / 蜂群 / real provider 长任务；只证明 **Phase 4 交付后主链与 Studio 不退化**。

| 项 | 结果 |
| --- | --- |
| CI 契约 pytest | **30 passed** |
| Studio run-detail smoke | **pass** |
| Studio north-star Inspector smoke | **pass** |
| Studio S8 续作 smoke | **pass** |

## Checklist

- [x] `pytest` — documentation_contracts · phase3_rolling · phase2_stability · north_star · session_continuation · chat_capability
- [x] `node studio/scripts/run-detail-smoke.mjs`
- [x] `node studio/scripts/north-star-inspector-smoke.mjs`
- [x] `node studio/scripts/s8-resume-continuation-smoke.mjs`

## 刻意 defer（有触发条件再开）

| 项 | 触发条件 | 原因 |
| --- | --- | --- |
| **A3 S7 clean re-run** | 本地 `model-check` 双 tier 通过 + 操作者显式发起 | 需 real provider；消除 [`S7-mvp-signoff`](./S7-mvp-signoff-20260606.md) 中 repair 循环 / 大体积 user_progress 技术债 |
| **A4 weekly rolling 复签** | maintainer 日历或 matrix 过期 | 非用户面阻塞项 |
| **Phase 5 / 蜂群** | [`SWARM_SANDBOX_RFC.md`](../deferred/SWARM_SANDBOX_RFC.md) 观察窗 + 灰度 | 仍 defer |

## 复现命令

```powershell
pytest tests/unit/test_documentation_contracts.py tests/integration/test_phase3_rolling_gate.py tests/integration/test_phase2_stability_gate.py tests/unit/test_phase2_stability_window.py tests/unit/test_north_star_storage.py tests/integration/test_status_long_horizon.py tests/integration/test_session_continuation.py tests/integration/test_chat_capability_manifest.py -q
node studio/scripts/run-detail-smoke.mjs
node studio/scripts/north-star-inspector-smoke.mjs
node studio/scripts/s8-resume-continuation-smoke.mjs
```

## 下一务实入口

1. **有 real provider 时**：A3 S7 clean re-run（`small_code_change` + `studio-benchmark` ≥0.8，run 状态 completed、无 repair 循环）
2. **无 provider 时**：保持本维护包定期复跑；不扩 scope
