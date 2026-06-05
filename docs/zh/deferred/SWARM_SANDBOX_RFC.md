# 蜂群 sandbox 并行写（Deferred — Phase 4+）

**状态**：已 defer；`disjoint_write` 真实 parallel 默认 **关闭**。

## 为何 defer

- MVP 证明编程 harness 单路径即可（Goal→Plan→Execute→Verify→续作）
- sandbox + promotion + merge + rollback 全链路 gate 未就绪

## 启动条件

1. Phase 2 MVP 闸门通过且稳定
2. sandbox 全链路 fake + 1 readonly 灰度通过
3. feature flag 可控放量

## 当前占位

- `disjoint_write_gate`：KEEP_PLACEHOLDER，不扩展实现
- `sandbox_backend`：KEEP_PLACEHOLDER
- CLI/配置中 parallel write 默认 `false`

## 参考

- 研发总计划 Phase 5、§6 KEEP_PLACEHOLDER
- ADR candidate workspace / merge gate
