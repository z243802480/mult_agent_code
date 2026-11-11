# S117 — 修复后的自然会话追加需求

2026-11-11 用户「继续下一批计划」，承接总计划 §16.2 第 29 项。已读 AGENTS、总计划 §6/§16.2、S116 brief/report 及现行 session_continuation / RunCommand / ExecuteCommand 的续作和预算恢复入口。

## 参考与边界

参考既有 session-agent 机制：续作追加新 task，保留已完成 task、原 run、历史账本和累计预算，跳过新的 GoalSpec/Plan；预算由 BudgetController.from_report 恢复。冷任务的空 read_scope 表示工作区内无该层读取门，PathGuard 和秘密/写权限另行执行。对照此前已调研的 [Anthropic 有效上下文工程](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) 的持久进度与按需上下文，不复制实现，不新增编排。

先确定性核对新任务的上下文读取、旧任务不变性及累计计量。若续作自身制造无依据的读取拒绝，红→窄修→绿后再冻结执行器；不迁移或改写 S116 原始任务/证据，不按目标文件名或模型能力补丁。

## 预定实验

从已接受的 S116 cachetools 工作区建立隔离续作副本；原工作区保持不变。这是有历史产物的自然追加需求，不能称全新独立仓库解题。公开追加目标为标准缓存家族新增批量非扰动读取 `peekmany(keys[, default])`，保留 peek/peekitems 的原公约。完整公约、独立 oracle 与目标文本在模型调用前固定哈希；检查器须自测合法表示及典型坏实现，旧 API oracle 作为兼容闸。

通过已有 `goal --continue-session` 进入同一 run；不手改 task、清账本、重置/提高预算，不预先规定工具导航，不提供解题提示或人为暂停。外部时限 3600 秒，正常 auto 权限与已配置真实路由。任何独立答案、oracle、运行时源码、相邻实验、凭证/网络访问暴露即拒收独立功能证明。

## 验收与停止条件

检查原任务/原账本前缀、累计费用与模型调用账本、输入/运行时哈希、允许改动范围、来源绑定、原测试和新回归、固定新旧 oracle，再正式 Review→Accept。分别审计调用账本和观察账本，计入执行前拒绝并核对 ID；记录 read_file 成功/拒绝与 next_offset/partial_line 是否触发、是否采用，未触发如实记录。

若出现通用工程缺陷，保留失败，先确定性复现再窄修，不追加同题重试刷绿。产品代码变更需相关测试、完整检查和精确 CI；仅实验/文档沿用不变生产 SHA 的 CI并验收新增检查器与文档。收尾更新计划、ACTIVE 和本机记忆；不外推一至三小时可靠性，独立 provider 未验收，keyed proof 保持 NOT RUN。

## 预调用登记

续作读取范围已确定性复现 1 红 2 绿，单行语义修复后相关/文档 32 过；新检查器 8 项正反例通过，WSL 相关 17 过，Ruff/类型棘轮无新增。仅把 follow-up read_scope 改为空，与冷 session 一致；写范围、PathGuard、旧任务和预算不动。公开文件哈希：

- `cachetools_peekmany_contract.md` SHA256 `dd3312eebf3ef6e24637af30281d47a7065ceabbb3a1ef08e41a3f2fe9967edd`。
- `cachetools_peekmany_oracle.py.txt` SHA256 `019d5c21724d6dc0eb36fe6c33a898d02900346dcda17ac093b0116b23981261`。
