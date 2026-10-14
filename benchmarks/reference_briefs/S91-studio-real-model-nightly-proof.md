# S91 — Studio 真模型 smoke 夜间证明

## 目的

把已有的 Studio keyed real-model smoke 从“本地手跑”纳入 nightly 证据链，补齐
1.2.166 已指出的 release/Studio 对接缺口。该切片只接 CI 观测面，不新增运行时、
路由或编排能力。

## 现状证据

- `studio/scripts/run-smokes.mjs --with-model` 已有独立 `REQUIRES_MODEL` 清单。
- `studio/scripts/{intent-routing,plan-output,orchestration-route-worker,b6-restricted-user-sim}-smoke.mjs`
  是真实模型 smoke，缺 key 时会诚实跳过。
- `verify.yml` 只跑 hermetic `npm run test:smokes`；`ring-recovery-nightly.yml` 只证明
  CLI/runtime 真栈。
- `release.yml` 已消费 ring-recovery 的最近一次结果，但 Studio keyed smoke 没有同级
  的稳定 job 或 release 可见摘要。

## 设计

1. 新增独立 `studio-real-model-nightly` job，直接运行现有三条跨平台 keyed smoke
   （intent-routing、plan-output、orchestration-route-worker），不把 provider key 带进
   per-push verify。B6 模拟脚本默认清理固定的 `H:/beta_user_sim/workspace`，只保留手动档。
2. 先显式检查 MiniMax + GLM 两把 key；缺 key 时 job 成功结束并在 Step Summary 写明
   `NOT RUN`，不能把“跳过”冒充通过。
3. 有 key 时运行三条跨平台 smoke，失败即 job 失败并上传 stdout/stderr 摘要；
   不新增重试或降级，保持真实失败可见。
4. Studio job 与 ring-recovery job 共享“有 key 才证明、无 key 诚实放行”的口径；
   本刀不把它直接并入 release gate，先建立连续 nightly 数据。

## 验收

- YAML 结构测试：job、双 secret gate、三条 smoke、summary 和 artifact 路径存在。
- 无 key 本地脚本分支可复现 `NOT RUN`，不跑 smoke。
- 有 key 的实际 CI run 作为后续证据；本地不伪造真实 provider 通过。
- `doc_contracts` 与 workflow 解析测试通过。

## 明确不做

- 不改 `run-smokes.mjs` 的 smoke 分类；B6 手动模拟不进入自动 nightly。
- 不把真实 provider 测试塞进 `verify.yml`。
- 不在本刀改变 release 的硬闸条件；等至少一轮 Studio nightly 证据后再评估。

## 实现记录

- date: 2026-10-14
- notes: 接入 `.github/workflows/nightly.yml`；本地 doc contract、YAML 结构和 smoke manifest 已验证。真实 provider 结果等待 CI nightly，不在本地伪造。随后修复两条本地 smoke 可复现噪声：preview websocket 的预期 `ECONNRESET` 收口；回放导出测试绕开桌面过滤器注入并继续拒绝未知外链。hermetic smokes 现为 40/40 通过。
