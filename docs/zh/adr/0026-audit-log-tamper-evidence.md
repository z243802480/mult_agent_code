# ADR-0026：`.asteria` 审计日志防篡改(append-only hash 链 · tamper-evident 首刀)

- 状态:Accepted(2026-07-13)
- 承:S77 商业化就绪审计 P1 硬缺口 / §3.3 designed-not-built / 战略分叉 C(可审计深度·用户拍板做)
- 相关:[[schema-dir-runtime-vs-packaged]](双份模板)

## 背景

运行时把决策/审批/工具调用/验证/进度全部写进 `.asteria/runs/<run>/*.jsonl`——**纯追加、无完整性保护**,任意进程可事后重写而无人能辨(S77 护城河论点自身的洞:"可审计"对规控买家通常=防篡改)。

## 决策

在**单一 append 咽喉** `JsonlStore` 上接入 **append-only hash 链**,给每个审计 JSONL 维护一个 co-located `<file>.chain` sidecar:

- 每条链项 `chain_i = sha256(chain_{i-1} + "\n" + sha256(record_i))`,把每条记录绑定到前一条。任何事后**编辑/删除/插入/重排**都会使重算的链发散,`verify` 精确指出断点。
- `append` 逐记录追加链项;`rewrite_all`(合法原子改写:决策状态转移/redaction)整体重链(绕过 rewrite_all 的裸编辑仍被检出)。
- **gating**:policy `audit.tamper_evident`(双份模板·**默认关**),`audit_chain.configure_from_policy` 在 run/execute 起手从 policy 设进程级开关。关时 `JsonlStore` 逐字节不变、零成本。
- 验证面:`asteria audit-verify [--run-id]`(maintainer·SUPPRESS)走 `verify_run` 报完整/篡改。

## 边界(诚实 · tamper-evident 非 tamper-proof)

- **做到**:tamper-**evident**——事后对审计日志的任何改动**可被检出**(是"证据被动过没有"的确定性检查)。
- **没做到(deferred)**:tamper-**proof**——链 sidecar 与日志同盘,有写权限的攻击者编辑记录后**重放整条链**即可绕过检测。彻底非重放需把**链头**锚定在攻击者够不到处(外部 notary / 签名 / 只读介质)。本刀产出的链头正是后续要外部锚定的那个值。
- 覆盖面:所有 `.jsonl` 审计文件(`.jsonl.chain` sidecar 自身天然排除)。in-flight 与 completed run 都逐记录链(非仅 run-end 快照)。

## 后果

- `storage/audit_chain.py`(新)+ `JsonlStore.append`/`rewrite_all` 各 3 行接入 + policy 双份模板 + `audit-verify` 命令 + conftest 进程级 flag 复位 fixture。
- 测试:7 单测(默认关无 sidecar / 开时验证完整 / 篡改-编辑 break_seq / 篡改-删除 length mismatch / rewrite 重链 / verify_run 聚合 / config-resolver)+ **真 glm 端到端**(reviewed_auto·flag on 的真 run 产 19 审计文件全链可验·篡改 user_progress 一条即检出)。全量 1225 绿·ruff/mypy 净。
- 默认关 → 离线/安全/性能零回归;开启 = 审计意识部署的 opt-in。

## 回滚

policy `audit.tamper_evident=false`(默认)即完全停用、无 sidecar、行为不变;删 `audit_chain.py` 接入三处即回退。
