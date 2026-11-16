# S131：Review 当前改动与逐项条件证据

日期：2026-11-16。执行真源：总计划 §16.2 / S131 brief。前次 [验证覆盖/预算报告](S131-verification-coverage-budget-20261116.md) 是历史快照。本刀最终源码 `e69b4b93e820a3fa050b886c72a6fdf924c80960`。

## 核实与边界

零新增模型审计前次 f5 失败样本：当前文件完整 **828 行 / 33155 字符**，5 条 GoalSpec 解释要求和任务 6 条 acceptance 均已送达；真实 Review 输入 98628 token。要求没有丢失，不能归因为字段未传。确切的数据缺口是：产物快照没有当前差异视图，已有两份真实写前备份及其工具观察未被用于聚焦。

本刀按用户要求修数据机制，**ReviewAgent 系统提示、共享验证指导与 EvalReport 输出契约均与前版逐字节相同**。没有新认知 JSON 阶段、领域解析、标题计数、provider 分支或新编排。

参考 [Codex 公开 Review target](https://github.com/openai/codex/blob/main/codex-rs/prompts/src/review_request.rs) 按变更基准组织审查的机制；本项目复用已有 FileBackupStore 和工具观察，并使用 Python 标准库 diff，不调用 Git、不读取 `.git`、不复制实现。

## 实现

同一份 schema 验证、来源绑定的 `current_artifacts` 增加 `review_focus`：

- **当前改动**：从当前 active 任务、当前 run 已记录的首次相关写前备份，与当前完整文件文本生成有界统一 diff；关联实际 task/tool/observation ID、manifest 引用及前后摘要。基线是工具前备份，不能宣称它一定是目标开始、用户 Git 基线或未经外部改变的版本。
- **逐项条件**：把已有 GoalSpec 描述/验收/完成条件和任务 acceptance 索引到原字段位置，标注 model_proposal / task_contract；不把解释中的 user 标签升级成用户权威。没有新造语义条件。
- **证据索引**：列同任务实际观察 ID，关系明确是“同任务”，不是“已覆盖某条件”。语义覆盖保持 unassessed，不按关键词猜映射、不因命令绿自动给每项打勾。
- **输入顺序**：只把当前产物及聚焦数据前置；完整文件、原始要求和独特历史证据仍保留。未把 Review 裁成只有 diff，也未改模型判定或现有审批保护。

读取基线先检查目标路径保护；内部读取只接受当前 run、严格备份标识和 FileBackupStore 的规范成员名，校验 manifest、身份、大小，禁止路径逃逸和链接访问。损坏、未知、其他 run/旧任务、超限或部分当前内容均保留 unknown，不改称“没变化”，不在首个损坏基线后偷偷改用后续已修改版本。该来源不是防磁盘篡改签名；diff 按文本行比较，不证明行尾字节保持或授权成立。

边界：最多 64 个写入观察、每 manifest/基线各 64 KiB、diff 共 32 KiB、条件最多 64 条/共 16 Ki 字符、每项最多 2048 字符、任务 16 个/每任务 32 个观察引用。截断、省略、未知均显式记录，完整账本仍在。根目录和内置 ReviewArtifacts schema 同步；现有权限、预算、范围及产物缺失保护不放宽。

## 首轮接线错误与实际修复

9b8a084 的生产回归先通过 Windows 35 / WSL 36，但最初实际副本 Review **18.01 秒 / 1 MiniMax，pass/0.98**。快照却显示 diff unavailable：调用的 `load_raw_tool_observations` 默认只返回尾 12 条，早期写入和备份引用已被裁掉。该轮不能算差异视图生效，更不能称语义修复；原副本、报告、模型记录和原件均保留。

e69b4b9 将聚焦采集器改为读取完整 schema 校验账本，原模型最近观察窗口保持。新增实际写入后 16 次读回的生产回归，确认即使模型尾窗没有 write_file，聚焦仍能找到真实早期基线。原真实数据零模型回放：**尾 12 条→unknown；完整 41 条→complete / 627 字符 diff**，基线摘要与预先冻结的原项目一致，29 条条件索引保持。没有增加提示词或补写观察。

中间 9b8a084 的全量测试因真实接线修复而停止，部分日志保留，**不记通过**。最终 e69b4b9 全量 **2007 passed / 6 skipped / 42 deselected，482.44 秒**，见下节。

## 修复后的真实负控

在同一个原 f5 失败现场的另一独立副本，用 e69b4b9 做一次标准 Review；正常输入，不给评估器或缺陷答案，不修改产物，不执行 Accept。实际 **15.89 秒 / 1 MiniMax，101867 输入 / 1493 输出 token**，返回 **pass/0.99，仍漏检真实缺陷**。

这次快照实际含完整 627 字符当前 diff、真实首次备份及 29 条条件；源/副本项目、工具账本和模型前缀保持，模型记录与新鲜快照 ID/ref 一致，token/预算对账。因此可以签“差异与条件数据已接通”，**不能签“语义漏检已修复”**。两次副本合计仅新增 2 次模型、202852 输入 / 2887 输出 token；继承的旧模型账本不当作新增调用。没有成本下降或因果稳定性的证据。

负控证据根：WSL `~/.cache/asteria-evaluations/s131-review-focus-negative-20261116` 和 `s131-review-focus-negative-v2-20261116`。原件仍为 `~/.cache/asteria-workspaces/s131-coverage-budget-tables`，两副本和原件分别识别，不能只用同名 run_id。

## 完整流程登记与状态

源码冻结后仅登记一次干净的同题完整流程：沿用原始名表目标、通用 AGENTS、项目基线、v1 诊断 / v2 独立判据及 13 控、32 iterations / 900 秒外部保险。评估器不在模型工作区，不提示标题答案、不在途中改命令/预算/产物或审批清理。只有独立示例、全项目、旧行/范围、身份/来源/计量全部合格，才正式 Review；工程保护后 pass 才复用新鲜报告 Accept。

本刀只改变 Review 数据，编码模型的提示和执行机制未变；新编码产物的变化不能归功于 Review 聚焦，也不以一轮结果证明统计收益。

工作区：`~/.cache/asteria-workspaces/s131-review-focus-tables`；证据根：`~/.cache/asteria-evaluations/s131-review-focus-tables-20261116`。

## 正向完整流程：独立合格后正式接受

单次原生 Goal **170.91 秒 / 14 MiniMax-M2.7**，completed；产物仅在 docs/usage.rst 插入合法小节，旧行保持、无额外用户文件。预先冻结的独立 v2 验收通过，示例 **9/9**、完整项目 **271 passed / 1 skipped**，章节/呈现/展示结果及范围均合格。没有更改失败样本、修改判据或中途给答案。

随后一次正式标准 Review **13.97 秒 / 1 MiniMax，71393 输入 / 1080 输出 token**，返回 **pass / 1.00**。实际输入绑定的新快照包含 **565 字符 complete diff / 37 条条件索引**；原始观察和首次备份对应。再以 `accept --skip-review` 复用该新鲜报告，**accepted=true / workflow_state=accepted / phase=ACCEPTED**，没有绕过失败报告或再次抽样评审。

累计 **15 次实际 MiniMax / 450657 输入 / 10375 输出 token**；**19 本地工具 / 19 唯一关联观察 / 19 收费 / 10 加权单位**，0 skill / MCP。模型/工具 ID、用量/预算、GoalSpec producer 及快照来源对账；content_preservation 实际提出。Review/Accept 后项目与工具账本、原模型前缀保持；原 f5 样本、源项目、fixture 和冻结 runtime 摘要不变。

本次方法修订、主动授权请求、范围事件反馈均 **0 次**，未触发的机制不冒充实证。成功样本与两个负控副本合计新增 17 模型 / 653509 输入 / 13262 输出 token；复制的历史调用不重复计费记账。

这证明本次**正向 Goal→执行→独立验证→标准 Review→Accept 整链实际完成**。它不能把已知坏产物的 pass/0.99 漏检翻绿，也不能归因于本刀让编码模型更会生成正确格式，更不证明稳定降本、跨 provider 或小时级可靠性。

主证据根保留 registration、输入/控制、原生终态、pre-review/final-result、review-report、实际 accept.log 和 final-lifecycle-audit；`post-goal-models` / `post-goal-tools` 支持新增评审与原前缀校验。负控和正控 run_id 可能相同，必须带工作区引用。

## 工程验证

初批 Windows **35 passed / 1 symlink skipped**、WSL **36 passed**；修复尾窗接线后新增生产生命周期两端各 **2 passed**。符号链接保护在 WSL 真路径验证，Windows 无创建权限则跳过；没有把跳过写成通过。测试准备的同名模块、原始字节/读取文本摘要和重复行 diff 假设均已在夹具层纠正，不是新模型实验结果。

最终 e69b4b9 Windows 完整 **2007 passed / 6 skipped / 42 deselected，482.44 秒**。Ruff 全仓及 mypy ratchet 无新增（60 已知 / 18 已不再报告）通过，未更新类型基线；最终源码五个离线基准通过，文档契约通过。原失败、DB、审批与在途计量不改写。

公开 GitHub API 核实最终运行时 Verify 仍 disabled_manually，0 run / 0 check-run，远端 **NOT RUN**；没有启用工作流、上传密钥或部署。

## 后续仍需收敛

当前完整文件、diff 和逐项条件已被真实请求消费，负控仍漏检，不能继续将它归结为未送达，也不再只调顺序或堆提醒。下一项先核实 Review 选择/消费独立可执行验证证据的能力与权限边界，复用现有工具机制；需要先有通用分离控制和确切缺口，不能把文档规则、某模型行为或本题答案写进 runtime。

本视图只覆盖有可用工具前备份的文本变化；shell 写入、候选合并等若没有相同来源，保留未知。它不具备 OS 隔离或防篡改签名。S131 正向整链已验，真实缺陷漏检仍开着；旧失败、DB、审批、预留预算和历史报告继续保留。
