# ADR-0010: Open Agent Loop and Evaluation Boundaries

日期：2026-06-09

## 背景

Asteria 在收敛执行耗时和 repair loop 时，曾把低模型调用数、低 repair 次数写成阶段闸门。这些指标适合发现简单任务的性能回归，但如果直接成为所有任务的 Runtime 硬限制，会产生错误激励：

- 模型为了满足次数限制过早停止，复杂任务失去自主推进能力。
- Runtime 为了避免计数超限，开始替代模型做语义决策。
- 每种失败被追加为专用 parser、gate 或 recovery 分支，形成规则堆积。
- provider 重试、schema retry、任务 repair 混用同一预算，归因失真。

公开机制调研显示，Claude Agent SDK 和 OpenCode 都允许 Agent Loop 默认运行到模型自行结束或用户中断，同时提供可选的 turns、steps、预算限制作为失控保险丝。Claude Agent SDK 达到限制后返回明确结果类型并允许恢复 Session。Codex 公开产品资料强调 sandbox、权限、迭代验证、过程证据和失败说明，而不是要求所有任务在统一轮数内完成。

行业评估实践同样区分：

- 结果正确性与安全边界。
- 任务效率、成本和用户体验指标。
- 防止无限运行的资源保险丝。

参考：

- [Claude Agent SDK: How the agent loop works](https://platform.claude.com/docs/en/agent-sdk/agent-loop)
- [Claude Agent SDK: Work with sessions](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [OpenCode Agents: Max steps](https://opencode.ai/docs/agents/)
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [OpenAI: Agent evals](https://platform.openai.com/docs/guides/agent-evals)
- [OpenAI: Evaluation best practices](https://platform.openai.com/docs/guides/evaluation-best-practices)

## 决策

Asteria 采用“开放 Agent Loop + 分层硬边界 + Eval/SLO 反馈”的长期策略。

```text
model -> tool -> observation -> model
          |
          +-> permission / sandbox / irreversible-action gate

loop telemetry -> eval / SLO / regression analysis
resource pressure or no progress -> compact / ask / stop / resumable limit
```

### 1. Runtime 硬边界只处理失控和不可逆风险

以下可以成为硬限制：

- 用户权限、protected paths、sandbox、网络和不可逆操作。
- 总成本预算、context hard stop、显式 deadline。
- 用户配置的最大 turns / iterations。
- 可证明的无进展循环：连续重复同类失败，且没有新 observation、artifact、verification 或决策信息。

达到资源限制时必须写明停止原因、保留 Session/Run 状态并支持 resume。不得把“达到限制”伪装成任务语义失败。

### 2. 模型调用和 repair 次数默认属于 SLO

以下默认是观测和优化指标，不是所有任务的完成门槛：

- model/tool calls。
- repair/replan 次数。
- 首次有效动作时间、总耗时和模型等待时间。
- strong route 使用率。
- 无产物调用比例。

简单任务可以设置严格的目标区间并触发性能回归告警；复杂任务和长任务允许更多回合，只要持续产生新证据并保持在安全、预算和用户授权边界内。

### 3. Repair 按失败归因计数

- provider/network/timeout/rate-limit retry 不计入任务 repair。
- schema/action retry 单独统计，不默认进入 DebugAgent。
- tool/verification/completion contract 失败才属于任务 repair。
- 相同失败没有新增证据时，进入 no-progress 判断；不是简单地因为 repair 次数达到统一小数字就停止。

### 4. Eval 决定产品收敛，不由单次运行决定

默认采用固定任务集、重复运行、配对对比和完整 trace：

- Golden Tasks 覆盖常见任务、边界任务和历史真实失败。
- 同一策略和候选策略在相同 provider、模型、workspace 与验证条件下运行。
- 每个关键 case 至少重复 3 次，比较成功率、P50/P90 耗时、调用量、成本、恢复和用户进展一致性。
- 新发现的真实 friction 进入数据集；不为单个样本直接增加专用规则。

### 5. 建议必须先完成证据检查

任何会改变 Agent 自主边界、默认执行路径、gate、预算或停止条件的研发建议，在进入计划前必须：

1. 阅读当前总计划、ACTIVE brief 和相关 ADR。
2. 调研至少一个成熟产品的公开机制或开源实现。
3. 写明该建议属于硬安全边界、资源保险丝、产品 SLO 还是实验假设。
4. 说明如何通过 eval 证明收益，以及失败时如何回滚或删除。

没有上述证据，不得把建议升级为 Runtime 默认策略。

## 复杂代码处置

现有代码不能按“行数多即垃圾”整体推倒，也不能因为已有测试就默认保留。S74 使用价值审计逐段处理：

| 分类 | 处置 |
| --- | --- |
| 保护用户安全、workspace 隔离、证据完整性 | 保留并收敛接口 |
| 能被真实任务证明改善完成率、耗时、恢复或可查证性 | 保留 |
| 仅服务维护者验证且不影响主路径 | 隐藏或冻结 |
| 与其他路径重复，或只为历史失败样本存在 | 合并、停用或删除 |
| 无明确 owner、调用入口、eval 或退出条件 | 不得继续扩展，进入删除候选 |

每次清理必须先建立行为基线，再删除一条路径并运行同一组 eval。禁止为了“代码更少”破坏已证明的安全和恢复能力。

## 结果

- Asteria 不再用统一低 model-call / repair 数量限制模型完成复杂任务。
- S74 的调用次数和 repair 数据用于比较策略、发现回归和决定默认路径。
- Runtime 保持必要护栏，但语义推进优先交给模型和 observation loop。
- 新增复杂度必须附带 eval、收益假设和退出条件；不能证明价值的复杂路径应冻结或删除。
