# ADR-0009: Layered Failure Attribution

日期：2026-06-04

## 背景

Asteria 前期把不少失败都汇入 `blocked -> debug -> repair/replan`，短期看可以恢复，长期会造成三类问题：

- provider 的 TLS/EOF/timeout 被误算成任务失败，消耗 DebugAgent 和 repair budget。
- 模型格式问题、工具执行问题、验证失败混在同一条 repair 链里，状态看似完整但责任边界不清。
- 为了处理宽泛输出不断增加 parser 和 gate 分支，主路径越来越慢、越来越不像成熟产品里的短会话流。

用户反馈指出：软件应该按分层体系持续完善，而不是每次围着失败尾巴补代码。这个 ADR 将失败归因变成 Runtime 的长期约束。

## 决策

Runtime 必须先归因，再决定恢复动作。默认边界如下：

```text
Provider/transport -> retry / connection check / provider fallback
Model schema/action -> schema repair / action preparer / one bounded retry
Tool/permission -> tool gateway / permission decision
Verification/contract -> repair | replan | ask | stop
Budget/context -> compact | budget decision | stop
```

### 1. Provider 失败不进入 DebugAgent

模型尚未返回可执行内容之前发生的错误，归属 provider 层：

- network / TLS / SSL / EOF
- timeout / deadline exceeded
- rate limit
- provider 5xx

这些失败应记录为 route/deadline/provider health evidence，并给出连接检查、retry 或 fallback 建议。除非已经拿到模型输出并产生了 tool observation，否则不得默认消耗 DebugAgent repair attempt。

### 2. Agent repair 只处理可行动失败

DebugAgent 和 repair loop 只处理以下对象：

- 已解析出的 action 不满足 schema 或 runtime policy。
- tool call 执行失败。
- verification 失败。
- completion contract 或 merge gate 阻断。

如果没有 tool observation 或 verification evidence，默认先回到 provider/route 层，而不是构造“虚假的任务修复”。

### 3. Gate 只守风险边界

Gate 不能为了追赶模型宽泛回答而不断增加细碎规则。新增 gate 必须说明：

- 所属层级：provider、schema、tool、verification、budget、context、permission、promotion。
- 阻断风险是什么。
- 降级或恢复动作是什么。
- 是否会影响简单任务 fast path。

### 4. 产品展示遵守 Active Next Step

Studio / status / gate-status 默认只展示当前可执行下一步，但不同产品面使用不同语言：

- Studio 主会话：用户语义，例如“模型连接中断，尚未写入文件；我可以检查连接并重试”。
- status：用户语义 + 受控动作，例如“检查模型连接 / retry”。
- gate-status / Inspector：维护者语义，可以包含 `model-check`、route、deadline 和 evidence refs。
- schema/action：repair action 或 bounded retry。
- tool/verification：debug、replan、ask 或 stop。
- budget/context：compact 或 decision。

历史失败留在 Inspector / evidence，不驱动默认主屏动作。

## 实现约束

- `ExecuteCommand` 捕获模型调用异常时，必须先用 provider failure classifier 区分 provider/network/timeout/rate limit/server error。
- `/run` 主循环遇到 retryable provider failure 时，不应自动进入 DebugCommand；应记录 provider blocker 并停止当前 loop，等待 provider health 或用户继续。
- `task_failures.jsonl` 可记录 provider failure，但 recommendations 必须说明它不是 DebugAgent repair。
- Real provider matrix 统计中，provider transient 不应被解释成任务语义失败。
- Studio 主会话不得直接展示 `provider route blocked`、`model-check`、route/deadline/gate 字段名；这些只能进入 Inspector 或按钮背后的受控 action。

## 验收

- 模型调用发生 TLS EOF 且没有返回 action 时，`task_failures.jsonl.failure_type` 为 `provider_network`。
- 同一 run 不应创建 `task_repair` model call。
- `user_progress.jsonl` 可以保留 provider failure evidence，但 Studio 主屏必须转成用户语义：“模型连接中断，尚未执行写入；可以检查连接并重试”。
- `status` 的下一步应显示“检查连接 / retry”，`gate-status` / Inspector 可以指向 `model-check`、retry 或 provider fallback。

## 结果

这条约束把“失败恢复”从单一 DebugAgent 通道拆回 Runtime 分层体系：provider 健康、schema/action、tool/verification、budget/context 各守自己的责任。后续如果再次出现慢任务或失败尾巴，先做归因审计，再决定是否改代码。
