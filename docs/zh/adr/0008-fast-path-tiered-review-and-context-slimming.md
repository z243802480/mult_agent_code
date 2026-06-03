# ADR-0008: Fast Path, Tiered Review, and Context Slimming

日期：2026-06-03

## 背景

真实 provider 小灰度显示，简单任务的大部分耗时不在工具调用、文件读写或 Runtime 调度，而在模型等待：强 `goal_spec`、强 `review` 和偏大的上下文包会把本该 2-3 分钟完成的小任务拉长到十几分钟。成熟产品的共同做法不是为每个失败尾巴继续堆规则，而是保持一条短、快、可恢复的主路径：

```text
Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop
```

Claude Code / Codex 风格值得吸收的不是具体界面复制，而是产品分层：

- 简单目标先走快路径，必要时再升级。
- 权限、sandbox、hook、approval 是执行边界，不是默认叙事。
- 工具过程进入会话流，raw evidence 进入 Inspector。
- 上下文默认瘦身，只把当前任务需要的材料交给模型。
- 失败先变成可执行的 repair / replan / ask / stop，而不是 provider/review 层的孤立日志。

## 决策

Asteria 后续研发采用“快路径优先 + 分层审查 + 上下文瘦身”的 Runtime 主策略。

### 1. Fast Path 优先

Runtime 必须先判断任务形态，再决定模型和审查强度：

| 任务形态 | 默认 goal spec | 默认 review | 上下文 |
| --- | --- | --- | --- |
| `doc_update` | deterministic 或 medium | deterministic | slim |
| `simple_file` | deterministic 或 medium | deterministic | slim |
| `single_file_bugfix` | medium | deterministic + 必要时 medium | slim |
| `complex_change` | medium，必要时 strong | medium/strong | focused |
| `high_risk` | strong | strong + gate | full/focused |

简单任务不应默认调用 strong route；强模型只在高风险、跨模块、权限/安全边界、验证失败后升级、release/acceptance 等场景使用。

### 2. Tiered Review

Review 不再等同于“每次强模型复审”。默认顺序是：

```text
deterministic verify -> medium semantic review -> strong review
```

只有 deterministic verify 不足、模型输出和证据冲突、风险等级升高、或用户/发布要求时，才进入更强审查。

### 3. Context Slimming

主路径模型调用默认消费瘦身上下文：

- 当前 goal / todo / selected task。
- 必要文件摘要和直接相关 diff。
- 最近 observation 和明确下一步。
- 预算、权限、风险边界摘要。

以下内容默认不进主路径上下文，只进 Inspector/evidence：

- 全量 route timeline。
- 全量 worker topology。
- 全量 model_calls。
- raw JSONL。
- 历史失败细节。

### 4. 复杂机制保留在正确层

已有 AgentLoop、RuntimeReadinessGate、worker、candidate workspace、promotion、merge gate、context budget 不是废弃能力，但必须按层使用：

- 主路径：快、短、可解释。
- 风险边界：权限、sandbox、merge/promotion、强 gate。
- Inspector：raw evidence、路线、上下文、worker、validation 细节。
- 发布/放量：完整 validation、强 review、真实 provider matrix。

## 约束

- 新增 gate 必须说明它属于哪个风险边界；不能为了解析模型宽泛回答而无限增加 parser 分支。
- 简单任务的性能回归必须被视为产品回归。
- Studio 主屏只能展示用户语义过程和结果；内部字段不得重新搬回主屏。
- provider 慢、超时或 streaming 失败优先调整 route/deadline/downgrade 策略，不把慢调用包装成更多 loop。
- 如果模型输出宽泛，优先简化 schema/prompt/任务形态，而不是继续写特殊规则兜底。

## 结果

研发权重调整为：

- 45%：Fast Path / Tiered Review / Context Slimming。
- 25%：Studio 会话主路径。
- 15%：Provider route/deadline 性能校准。
- 10%：Inspector / Evidence 查证层。
- 5%：Subagent / sandbox / parallel 放量前置。

衡量标准：

- 简单文件/文档任务目标耗时接近成熟产品的分钟级体验。
- 强模型调用次数随风险升高，而不是随每个任务固定出现。
- 用户只看主会话也能知道“做了什么、验证了什么、下一步是什么”。
- Inspector 能查账，但不支配主路径。
