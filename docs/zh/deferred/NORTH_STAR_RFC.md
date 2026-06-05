# North Star 长目标（Deferred — Phase 3+）

**状态**：已 defer，仅 S7 MVP 闸门连续稳定 2 周后才启动 RFC。

## 为何 defer

- Phase 1–2 优先完成 harness + Studio 会话 MVP（`small_code_change` benchmark + real provider）
- North Star 需要跨 run milestone、`north_star.json` 与 Active Next Step 产品化，依赖稳定的 `user_progress` / `runtime_progress` 契约

## 启动条件（来自研发总计划 §10）

1. S7 studio-benchmark `small_code_change` ≥ 0.8
2. real provider scoped cases 连续通过
3. Phase 2 稳定 2 周

## 预期产物（RFC 阶段，非当前实现）

- `north_star.json` schema + workspace-local 存储
- CLI/Studio 只读 North Star 摘要（非 gate 主屏）
- 跨 ≥3 run milestone 追踪

## 参考

- 研发总计划 Phase 4、§1 North Star
- OpenCode utw 思路（机制摘要见研发总计划 §5）
