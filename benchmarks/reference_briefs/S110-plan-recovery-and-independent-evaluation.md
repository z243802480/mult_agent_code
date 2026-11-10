# S110 — 规划错误有界反馈与独立实跑

用户 2026-11-10「继续推进下一步吧」，承接总计划 §16.2 / S109 报告。已读 AGENTS、总计划 §6/§16.2、S109 brief/report。S109 的失败、解答暴露和固定 oracle 11/12 保持原记录。

## 参考与范围

- [OpenCode SDK 官方结构化输出说明](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/sdk.mdx) 描述 schema 校验、有限 retryCount 与耗尽后的结构化错误；此处只借鉴边界，不据文档断言其历史实现每条重试都接通。
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 区分约束生成与应用校验。本刀沿用现有跨 provider JSON 通道，保留应用 schema；不翻原生 transport、不绑定单一模型。
- 本仓库 model_driven_turn 已有实际协议错误回灌；PlanAgent.generate 则在第一次 JSON/任务形状/最终 schema 不合格时直接抛错回模板，这是 S109 真跑观察到的缺口。

只改 PlanAgent 的有限反馈与 PlanCommand 的原诊断接线：初次 + 最多一次模型纠正；原目标/指导/角色/权限/预算不变，错误与限长原响应交回同一模型，由模型重出完整计划。每次响应仍走原解析、归一化、profile 和最终 schema。混合非对象任务不能悄悄丢弃；不猜改模型任务含义、不放宽持久化 schema。provider/预算异常不当格式错重试；仍使用原计量客户端，耗尽照旧可见回模板，offline 入口保留。成功纠正也需在事件/Inspector 留痕，不能伪称首轮有效。

## 实验与验收边界

先写通用隔离协议，再固定一个与 Asteria 执行器无关的公开真实仓库快照及目标。候选 TinyDB 的 update_multiple 批次失败一致性，先以真实源码/原测试确认可测范围；无对应正确实现存于执行器。目标、允许改动、行为判据和等价表示在调用前固定，保留输入及独立脚本哈希。不得向模型提供修复实现或隐藏测试；不得运行后改判据刷绿。

执行器与目标/隐藏验收分别存放，目标无 .git、执行器副本、修复参考或控制脚本。目标指令明确禁止查看执行器/安装库实现、父目录/其他实验及隐藏验收作答案；正常调用 Python/pytest 允许。此为实验布置与行为审计，不冒称 OS 安全隔离，不重开本地强沙箱。记录越界参考读取即否决独立证明；不把“无人手改”当“没有解答暴露”。

## DoD 与停止条件

1. RED→GREEN：坏 JSON→有效模型计划、schema/profile 错→纠正、连续两错→原 fallback；成功计划仅一次调用，provider/预算拒绝无额外纠正，超长回灌受限，原请求/目标不被改写。
2. PlanCommand 真存储路径中，纠正与最终模型/模板来源可观察，调用计量与预算拒绝实际覆盖；原文档/安全/任务契约回归通过，完整 Python、Ruff、类型棘轮及精确代码 CI。
3. 固定一次独立真实目标，通过旧测试和预定义独立行为验收、原输入哈希/范围审计才 Review→Accept。字段名只有属于公开任务契约才固定；否则按行为/语义允许等价实现。单次最多 60 分钟和默认预算，不人工改解答/给修复提示；缺 key/暂停/失败如实记录，不刷样本。

ACTIVE_SLICE=S110。工程接线与定向回归已过；公开 TinyDB 目标和固定行为 oracle 已预注册，精确 CI 与一次真实实跑待验收。
