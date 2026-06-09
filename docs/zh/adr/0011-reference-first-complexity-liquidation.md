# ADR-0011: Reference-First Complexity Liquidation

日期：2026-06-09
状态：Accepted

## 背景

Asteria 的愿景成立：构建 local-first、可恢复、可验证、可审计的通用长任务 Agent Harness。问题可能出现在实现过程，而不是愿景本身。

自研系统容易出现两种同样危险的偏差：

1. 因为成熟产品没有某项机制，就放弃真正有价值的差异化愿景。
2. 因为某项机制属于自研愿景，就保护已经被证明复杂、低效或劣质的实现。

成熟 Harness 的公开机制提供了可复用的驾驭方式：

- Claude Agent SDK：稳定主循环是 `model -> tool -> observation -> model`；权限、hooks、session、compact、subagent 和 resumable limits 位于清晰边界。
- OpenCode：Agent、工具和权限以声明式配置组合；最大 steps 是可选保险丝，不替代模型推进。
- Codex：以 sandbox、可验证工具执行、测试结果、任务隔离和用户审查形成产品闭环。
- Anthropic 的工程建议：优先简单、可组合模式，只在复杂度带来可测收益时增加复杂编排。

这些产品不是 Asteria 的功能上限，但它们是实现质量的参考下限。Asteria 可以拥有独特能力，不能用独特愿景为劣质实现辩护。

参考：

- [Claude Agent SDK: Agent loop](https://platform.claude.com/docs/en/agent-sdk/agent-loop)
- [Claude Agent SDK: Permissions](https://platform.claude.com/docs/en/agent-sdk/permissions)
- [Claude Agent SDK: Hooks](https://platform.claude.com/docs/en/agent-sdk/hooks)
- [Claude Agent SDK: Sessions](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [OpenCode Agents](https://opencode.ai/docs/agents/)
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [OpenAI: Introducing Codex](https://openai.com/index/introducing-codex/)

## 决策

Asteria 对所有复杂机制实施 Reference-First Complexity Liquidation。清算不是按行数删代码，而是对每条行为路径进行严格裁决。

### 1. 愿景与实现分离

审计对象必须拆成两层：

```text
Product capability / invariant
  例如：长任务可恢复、candidate 隔离、模型可使用 subagent

Current implementation
  例如：专用状态机、重复 summary、强制动作映射、双 transport
```

能力有价值，不代表当前实现必须保留。确认实现劣质后，应保留能力契约，删除实现，并优先采用成熟产品已经证明的驾驭方式重建。

### 2. 四道裁决门

每条默认或候选路径必须依次通过四道门。任一道不通过，都不能继续扩展。

#### Gate A：产品必要性

必须回答：

- 它解决哪个真实用户问题或 Asteria 核心不变量？
- 删除后用户失去什么？
- 是否存在真实入口、真实使用者或明确安全责任？

裁决：

- 无真实问题、仅为内部对象完整性存在：删除候选。
- 只服务未来设想：冻结为 placeholder，不得扩展。
- 属于安全、恢复、隔离或可验证交付核心：进入 Gate B。

#### Gate B：成熟参考与机制合理性

必须至少研究一个成熟产品的公开机制或开源实现，并回答：

- 成熟产品使用哪些稳定原语驾驭同类问题？
- Asteria 能否直接复用这种机制、接口形态或控制边界？
- 如果采用不同实现，差异是否来自 Asteria 独特需求，而不是不了解成熟做法？

裁决：

- 已有成熟简单机制，而 Asteria 使用更多专用状态、映射或分支且无优势证据：判定为劣质实现候选。
- 不同实现有明确独特需求和实验假设：进入 Gate C。
- 无 reference brief：禁止修改默认路径。

#### Gate C：可测产品收益

必须通过相同任务、相同 provider、相同 workspace 和相同验证条件的配对 Eval，证明至少一项：

- 提高完成率或结果质量。
- 降低用户等待、模型成本或无效回合。
- 提升安全、隔离、恢复或可查证性。
- 解锁成熟产品没有覆盖、但属于 Asteria 愿景的真实能力。

裁决：

- 无可测收益：默认关闭、冻结或删除。
- 收益只在窄场景成立：保持 opt-in。
- 收益稳定且维护成本合理：可进入默认路径。

#### Gate D：实现质量与可替换性

即使产品能力有效，当前实现仍必须满足：

- 单一 owner 和单一真源。
- 清晰层级，避免 Runtime、命令、Studio 重复做同一语义判断。
- 能通过 feature flag、adapter 或稳定接口替换。
- 有 focused tests、Golden Trace、failure attribution 和退出条件。
- 新失败不要求继续增加同类特殊分支。

裁决：

- 能力有效但实现不合格：保留契约，删除并替换实现。
- 实现与能力均不合格：直接删除。
- 实现合格：保留并持续 Eval。

### 3. 劣质实现判定信号

出现以下任意强信号，应进入清算，不得继续局部修补：

- 成熟产品用稳定原语解决，而本系统使用大量专用映射、状态和规则。
- 同一语义在多个层重复推导或互相覆盖。
- 为单个历史失败、模型措辞或 provider 异常增加长期默认分支。
- Runtime 在没有安全原因时替代模型做语义决策。
- 测试主要证明内部 JSONL/状态存在，不能证明用户任务更好。
- 功能只有 fake probe、maintainer command 或自证闭环，没有真实产品入口。
- 每次修复都会引入新的兼容分支、summary 投影或 gate。
- 无法说明删除后用户会失去什么。
- 无法建立与默认路径的配对 Eval。
- 维护成本和认知负担持续增长，但成功率、速度、安全或恢复没有改善。

### 4. 删除强度

清算结论只有以下五种，不允许长期停留在模糊的“以后优化”：

| 结论 | 动作 |
| --- | --- |
| KEEP_CORE | 核心不变量和实现均成立，继续维护 |
| REPLACE_IMPLEMENTATION | 保留能力契约，删除劣质实现，采用更简单机制重建 |
| OPT_IN | 有窄场景价值，退出默认路径 |
| FREEZE | 未来可能有价值，但当前无证据；禁止扩展 |
| DELETE | 无产品必要性、无收益或被更好路径取代，删除代码、测试、文档和入口 |

确认 `REPLACE_IMPLEMENTATION` 或 `DELETE` 后，沉没成本不能成为保留理由。

### 5. 证据负担

- **新增复杂度者承担证明责任**：必须提供 reference、真实任务、配对 Eval、owner 和退出条件。
- **默认路径承担更高证明责任**：不能只证明可运行，必须证明优于更简单方案。
- **删除安全核心者承担证明责任**：权限、sandbox、workspace 隔离、candidate/promotion、可恢复状态和验证证据不得在无等价替代时删除。
- **独特能力承担持续证明责任**：Asteria 特有能力必须周期性证明真实产品收益。

### 6. 清算执行纪律

1. 先记录能力契约和当前 Golden Trace。
2. 找到成熟参考的最小稳定原语。
3. 标记当前实现的重复责任、分支、入口和依赖。
4. 先停止扩展，再通过 flag/adapter 隔离旧实现。
5. 用更简单路径完成配对 Eval。
6. 确认结果、安全和恢复不退化后，删除旧代码、测试、文档、schema 和入口。
7. 删除完成后更新清算登记表；禁止保留无调用的“备用实现”。

公共契约需要迁移时遵守 deprecation policy；内部实现和未发布实验路径确认无调用后可以直接删除。

## 后果

- Asteria 的愿景和核心不变量受到保护，但任何具体实现都必须接受参考与证据审判。
- 成熟产品的优秀驾驭方式成为默认起点，而不是开发完成后的装饰性调研。
- 复杂能力可以存在，但默认路径必须证明比简单组合更有价值。
- 确认劣质实现后，团队应果断删除，而不是继续围绕它修补。

## 回滚或替代条件

如果被删除路径后来出现新的真实用户需求，只能作为新的 Reference-First Slice 重建；不得直接恢复旧实现。重建仍需通过四道裁决门。
