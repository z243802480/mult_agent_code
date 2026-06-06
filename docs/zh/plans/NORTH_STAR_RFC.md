# North Star 长目标 RFC（Phase 4）

**状态**：RFC 已开启 — 实现 blocked 至观察窗 **2026-06-20**  
**窗口契约**：[`benchmarks/phase2_stability_window.json`](../../benchmarks/phase2_stability_window.json)  
**Slice brief**：[`benchmarks/reference_briefs/S11-north-star-v1.md`](../../benchmarks/reference_briefs/S11-north-star-v1.md)  
**入口日期**：2026-06-06（S7 + rolling + 稳态签字完成后）

## 1. 背景

North Star 是 **跨 run 的远端目标**（OpenCode utw 思路），与当前 run 的 plan/tool/verify 叙事分离。Harness MVP 与 Phase 3 稳态已签字，RFC 合法入口已开；**代码实现**须等 2 周观察窗结束。

## 2. 启动条件

| 条件 | 状态 |
| --- | --- |
| S7 `small_code_change` ≥ 0.8 | ✅ |
| Phase 3 rolling 三门禁 real provider | ✅ |
| Phase 2 scoped 稳态 | ✅ |
| 连续稳定 2 周 | 🕐 2026-06-06 → **2026-06-20** |

`status --json` → `long_horizon` 投影进度。未满窗 **禁止** 写 `.asteria/north_star.json`。

## 3. v1 范围

**In scope**：`north_star.json` 持久化；`status` / `handoff` 只读摘要；≥3 run milestone 链接；schema 校验。

**Out of scope**：蜂群 parallel（[`deferred/SWARM_SANDBOX_RFC.md`](../deferred/SWARM_SANDBOX_RFC.md)）、自动 execute、gate 主屏、SQLite。

## 4. 数据模型

路径：`.asteria/north_star.json` · Schema：[`schemas/north_star.schema.json`](../../schemas/north_star.schema.json)

## 5. 实现切片（2026-06-20+）

| Slice | 内容 |
| --- | --- |
| S11a | 存储 + schema + unit tests |
| S11b | status / handoff 只读投影 |
| S11c | accept / handoff 链接 run |
| S11d | Studio Inspector 只读（可选） |

## 6. 验证

```powershell
pytest tests/unit/test_phase2_stability_window.py tests/integration/test_status_long_horizon.py -q
python -m asteria_runtime status --json --root .
```

窗口打开后追加 north_star 存储与集成测试。

## 7. 参考

- [`研发总计划.md`](../研发总计划.md) Phase 4、§1 North Star
- [`当前状态与路线.md`](../当前状态与路线.md) §4 综合下一步计划
