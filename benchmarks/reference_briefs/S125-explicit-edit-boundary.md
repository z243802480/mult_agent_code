# S125 — 明确编辑边界的传递与执法

2026-11-11 用户「继续下一项」，承接总计划 §16.2 第 37 项。已读 AGENTS、总计划 §6/§16.2、S124 报告和真实 scope-probe；原 S124 未发生越界写，不虚构事故。

## 参考 → 落点 → 不照搬

- [OpenCode permissions](https://opencode.ai/docs/permissions/)：把 edit 的目标资源与 read、shell 分开判断，多文件 patch 任一路径拒绝就拒绝整体。落点：结构化 GoalSpec 编辑边界、任务有效写范围、编辑工具及 merge gate；不复制其配置格式或从任意 shell 文本猜所有副作用。
- [Codex-rs 权限模型](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs)：结构化写根与执行权限是独立事实。落点：允许开放目标自主选文件，显式限定只作为权限上限。不在本刀重做 OS 沙箱，不把 task path guard 称为任意命令强隔离。

## 设计与兼容范围

GoalSpec 新增可选 edit_boundary：mode=open/restricted，paths 为精确相对路径；目录以 / 结尾，不做 glob/关键词猜测。模型负责把用户语义分类，Runtime 验证结构与路径、传递并取交集；产物列表不等于排他编辑授权。旧有效 GoalSpec 缺字段仍兼容原行为，新提示要求显式给出边界；不声称旧会话天然拥有结构化限制。格式纠正沿用原两次上限；无法解析安全边界的 fallback 不授予写路径。

明确边界进入任务后，session_agent 扩写、测试授权、后续范围审批不能移除这个上限；读上下文不因只限编辑而被误收窄。路径按精确文件/目录语义判断，保护空集只读、Unicode/空格与非标准仓库目录。编辑工具在实际修改前检查，多文件 patch 不得部分修改后才发现拒绝；merge gate 再查实际产物。保护路径与 shell 风险策略独立保持。

同 run 暖续作保留既有明确边界，不因深拷贝任务又扩写而丢失；新自然语言续作不在此模块按词典猜一份新边界，真正改变授权需重新理解目标。子任务继承上限，不能用子任务提出的更大 write_scope 绕过。允许已授权范围内的验证和只读探索，不增加编排 Wave、工具或权限档。

## 验收

先以 S124 固定 GoalSpec/任务重现“只有两份文档却允许源码/测试”，验证模型/确定性规划、冷/暖任务、实际写工具、多文件 patch、merge gate、审批扩大原 scope 后仍受限。开放/旧任务保持可探索；坏路径/坏边界不扩大授权，持久化必须经 schema，根目录与包内 schema 同步。

相关 Windows/WSL、完整 Python、Ruff/类型及离线基准。随后一个预登记新真实目标：从已接受 S124 源码复制无 .asteria 副本，仅修改 usage 增补自包含 dry-run 示例，其他内容/实现/测试保持；不迁移旧任务或提供解法。真实 guarded 同环境预检、冻结输入/执行器、默认 profile/provider、原预算权限、900 秒外部上限。观察模型生成边界及真实计划的最终范围，独立执行文档示例、审计工具与哈希，通过才正式 Review→Accept；不把受控拒绝探针冒充模型自然越界。

收尾更新主计划、ACTIVE、报告和记忆。远端 UI 若因镜像 DNS 未运行仍如实保留，不顺手改 workflow。
