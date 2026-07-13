# Slice — .asteria 审计日志防篡改(tamper-evident hash 链 · S77 P1)

用户直接授权(战略分叉 C:可审计深度)。目标:关掉 S77 护城河洞——审计 JSONL 纯追加、可事后重写而无人能辨。

## observed_pattern(行业已验证)
- **Certificate Transparency / 区块链-lite / 审计日志**:append-only hash 链——每条记录绑定前一条,任何事后改动使链发散、可检出。规控买家的"可审计"通常=防篡改。
- **单一 append 咽喉接入**:不在 60 个 append 站点逐个改,在 `JsonlStore` 一处焊。

## asteria_mapping(我们怎么做)
- 文件:`storage/audit_chain.py`(新)——`append_chain_entry`/`rechain_file`/`verify_file`/`verify_run` + `configure_from_policy`。
- 接入:`JsonlStore.append`(逐记录追加链项·用刚写的确切字节)+ `rewrite_all`(合法原子改写整体重链)各 3 行;`is_audit_file` = 所有 `.jsonl`(`.jsonl.chain` sidecar 天然排除)。
- gating:policy `audit.tamper_evident`(双份模板·**默认关**);`configure_from_policy(policy)` 在 `RunCommand.run` / `ExecuteCommand._execute` 起手设进程级开关;conftest autouse fixture 每测复位防泄漏。
- 验证面:`asteria audit-verify [--run-id] [--json]`(maintainer·SUPPRESS)→ `verify_run` 报完整/篡改+断点。
- O(1) 链头:`_last_chain_hash` 有界 tail 读(链项小),避免每 append 全读。

## do_not_copy / 边界(诚实)
- **tamper-evident 非 tamper-proof**:链 sidecar 同盘,攻击者编辑记录+重放整条链可绕过检测;彻底非重放需外部锚定链头(notary/签名/只读介质)——deferred,本刀产出的链头正是后续要锚的值。
- 不在 append 站点逐个改(用中央咽喉);不默认开(离线/安全/性能零回归·opt-in)。

## 验证
- 7 单测:默认关无 sidecar / 开时验证完整 / 篡改-编辑→break_seq / 篡改-删除→length mismatch / rewrite 重链 / verify_run 聚合 / config-resolver。
- **真 glm 端到端**:reviewed_auto·`audit.tamper_evident=true` 的真 `asteria run` 完成 → **19 个链式审计文件全部 verify OK**(events 37·user_progress 342·tool_calls·capability_decisions·runtime_hooks…);篡改 user_progress 一条 → audit-verify 检出(record-hash-diverged @seq2)。
- 全量 1225 passed(仅 6 既有失败·无关)·ruff/mypy 净。**须 worktree PYTHONPATH**(editable 装指向主副本·见记忆坑⑥)。

## 实现记录
- date: 2026-07-13
- notes: ADR-0026 + §16 v1.2.30 + §3.3/§110 缺口划掉。S77 三硬缺口:自主环默认✅/审计完整性✅/OS 沙箱仍缺。
