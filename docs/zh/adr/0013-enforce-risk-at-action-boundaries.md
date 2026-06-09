# ADR-0013: 在动作边界执行风险护栏，删除全局 RuntimeReadinessGate

日期：2026-06-09  
状态：Accepted

## 背景

`RuntimeReadinessGate` 最初用于汇总 route、deadline、context、capability、Agent Loop、
subagent、candidate promotion 等证据。随着能力增加，它增长到约 1800 行，并开始同时承担：

- 发布前验收；
- Runtime 安全判定；
- 历史证据完整性审计；
- validation probe 结果判定；
- 内部 JSONL 一致性检查；
- 恢复命令推荐。

这造成了一个反常结构：真正的权限、sandbox、merge 和 promotion 风险已经在动作边界受到
保护，但系统仍会在事后扫描全部内部证据，并用一个全局 Gate 再次决定 Runtime 是否可用。
`validation-run` 还需要维护 probe 白名单，绕过由自身目标证据触发的 readiness block。

成熟 Harness 的公开机制更简单：

- Claude Agent SDK 的主循环是 model -> tool -> result -> model；权限在每次工具执行前判定，
  被拒绝的结果回流给模型。
- Codex 使用 sandbox mode 和 approval policy 约束模型生成的动作；review 用于查证变更，
  不作为所有 Runtime 内部对象的总闸门。
- Session、trace、validation 和 eval 用于恢复、观测与产品校准，不替代动作边界护栏。

参考：

- https://platform.claude.com/docs/en/agent-sdk/agent-loop
- https://platform.claude.com/docs/en/agent-sdk/permissions
- https://platform.claude.com/docs/en/agent-sdk/sessions
- https://developers.openai.com/codex/agent-approvals-security
- https://developers.openai.com/codex/app/review

## 决策

删除全局 `RuntimeReadinessGate` 实现及其控制面字段。

责任重新归位：

| 责任 | 唯一执行位置 |
| --- | --- |
| tool、网络、写入、越权风险 | Tool Gateway / permission / sandbox，在动作发生前执行 |
| candidate、merge、promotion、不可逆操作 | 对应 gateway / merge gate / promotion gate |
| provider route 与发布环境 | doctor、model-check、gate-status 的 release preflight |
| validation 与 acceptance | validation-run、real-model acceptance、paired eval |
| Agent Loop 恢复 | Session loop 消费 observation 后由模型决定 repair/replan/ask/stop |
| evidence/schema 一致性 | focused tests、schema validator、Inspector diagnostics |
| context pressure | session 自动 compact、可恢复 hard-stop；不阻断无关发布判断 |

`gate-status` 只回答维护者发布问题：当前环境、真实 provider gate、validation suite、
core acceptance、promotion/plugin 发布风险是否允许扩大验证。它不再重新审计每个 Runtime
内部对象。

`validation-run` 的 probe 直接检查目标行为证据。例如 readonly 写入 probe 检查动作是否被
拒绝，disjoint write probe 检查 unsafe dispatch 是否被拒绝；不再通过全局 readiness check
间接证明。

## 保留的不变量

- protected paths、permission、sandbox、candidate workspace、merge、promotion 和 remote
  action 护栏不得削弱。
- 发布放量仍要求真实 provider、validation suite 与 core acceptance 证据。
- 缺失目标 probe 证据仍使 targeted validation 失败。
- schema 校验和 durable evidence 继续保留，但缺少无关 evidence 不再使整个 Runtime blocked。

## 后果

- 删除约 1800 行 RuntimeReadinessGate 和约 1800 行自证测试。
- 删除 `validation-run` 的 readiness bypass 白名单。
- 控制面不再输出 `runtime_readiness_gate`。
- 新增安全规则必须明确落在具体动作边界；禁止重新建立全局内部完整性总闸门。

