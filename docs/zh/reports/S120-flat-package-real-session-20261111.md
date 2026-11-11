# S120：flat 包真实新会话，功能通过、严格范围失败

日期：2026-11-11。执行入口与冻结输入见 [S120 brief](../../../benchmarks/reference_briefs/S120-flat-package-real-session.md)。

## 结论

普通 init→goal 确实建立了 `session_agent` 新会话，flat 包内 `write_file` 真正成功；快照功能的固定独立检查与旧功能检查全过。但模型额外创建了不在公约范围内的字面文件 `tinydb/_snapshot.py（仅在实现需要时）`，所以**第一阶段独立验收失败，第二阶段 NOT RUN（零新增调用）**。原失败文件、任务和账本全部保留；不重跑刷绿、不迁移旧 profile、不做外部正式 Review/Accept。

Runtime 自身状态是 completed / ACCEPTED（自动接受），`review_status=unknown`。这是运行时自己的结论，不能替代本次更严格的独立验收。

## 输入与实际执行

- 执行器固定 `4c6cb98`，登记提交 `f1690b8`；执行前基线的精确 Verify `42995602110` 三 job 通过。仅导出 src/schemas，执行后字节不变。
- 起点是 S113 已接受的 TinyDB readonly 源码产物（MIT，上游 `edff96aeb2616402e9489d46e90a592c05565621`）。复制时排除旧 `.asteria` 和缓存；不是干净上游新解题，也不继承旧 harness 会话。原 S113 源码与状态哈希均未变。
- 两阶段目标、公约和检查器在首次调用前冻结；共享 3600 秒外部上限与原预算，未提高或重置计量。原完整目标在本轮只执行一次，无人工提示、暂停或代码代修。
- 新工作区 `~/.cache/asteria-workspaces/s120-tinydb-session`；run `run-20261111-0001`；原始外部证据在 `~/.cache/asteria-evaluations/s120-flat-session-20261111`，不进仓库。
- 执行 **244.20 秒**；35 次真实 MiniMax-M2.7 调用，输入 1,280,823 / 输出 22,802 tokens。cost_report 与原始调用记录逐项一致，within_budget。没有做不等价目标之间的效率比较。

| 检查 | 实际结果 |
| --- | --- |
| 新 API 基线 | 11 个 oracle 方法均失败（含子场景共 16 failures）；基线没有 snapshot API |
| 原功能基线 | readonly oracle 20/20；项目 236 passed / 1 skipped |
| 最终新 API | 固定 snapshot oracle 11/11 |
| 最终旧功能 | readonly oracle 20/20；项目 245 passed / 1 skipped（新增 9 项） |
| 导入绑定 | tinydb 来自本工作区源码 |
| 文档与测试审阅 | usage/API 都更新；旧测试字节不变，新测试非空断言；实现与独立公开行为一致 |
| 严格编辑范围 | 失败：新增一个不允许的字面路径；没有用测试全绿覆盖此结果 |
| 正式 Review/Accept | NOT RUN：前置独立范围检查失败 |
| 同 run 自然追加 counts | NOT RUN：前置阶段未验收，0 新调用；不能证明续作成功 |

原文件修改为 `tinydb/database.py`、`docs/usage.rst`、`docs/api.rst`；新增 `tests/test_snapshot_s120.py`、允许的 `tinydb/_snapshot.py` 和上述越界文件。其它源码、配置、旧测试、LICENSE、AGENTS 和两份公约未变。

## 实际工具与自主恢复

101 条工具执行与 101 条观察逐一同 ID，ID 唯一；48 read_file、14 search_text、10 apply_patch、12 run_command、3 write_file、8 run_tests、6 todo_write。0 denied，5 failure：一次 patch 形式无效、三次新测试失败、一次文档 patch 上下文不匹配。模型在同一执行循环内自主修复；测试错误涉及错误调用 remove 和测试替身初始化，未修改旧测试逃避验收。

人工核对全部 101 条工具输入、10 次 patch 目标、shell 命令、最终源码/文档和新增测试，未发现读取外部答案、执行器源码、安装包实现、其它实验、秘密或网络。`toolcall-0088` 在 flat 目录成功写正常辅助模块，证明 S118 写目录范围机制被实际触发；`0095` 写出的额外文件则导致范围失败。

本次没有触发 S119 的未闭合验证命令 pre_final 反馈（计数 0），没有自动 replan，也没有 verified-noop 修复任务。不能拿本轮证明这些机制的真实恢复效果。新文件读取提示没有强制触发；保持自然采样。

## 根因与本刀通用提示修正

原 GoalSpec 把 `tinydb/_snapshot.py only if needed` 列入 target_outputs。Planner 将其翻译成 `tinydb/_snapshot.py（仅在实现需要时）`，同时写入 expected_artifacts / expected_changed_files。pre_final 对计划的字面路径做存在性检查，在第 26、29 轮分别发出 `upe-2011`、`upe-2202` 缺失产物反馈；模型先抽出正常辅助模块，再补出带说明的文件以满足元数据。

不应靠删除中文/括号/特定后缀来修，也不应放宽真实缺失交付物检查。本刀仅更新两个角色的通用提示：

1. GoalSpec 区分“允许改”与“必须交付”，条件方案留在约束/需求说明。
2. Planner 明确 expected_artifacts 是逐项存在性承诺；只列所选实现真正必需的产物，路径不拼说明。面对混杂 GoalSpec 仍须回到原始用户公约，保留字面 Unicode/标点名称。

没有修改路径解析、完成守卫、权限范围、schema、provider 行为或执行栈；没有为该 API 固定实现。补充存在/缺失的合法中文、括号路径回归，确认守卫仍按完整字面名称执法。提示修正具有概率性，不是对未来错误计划的硬保证。

另做**隔离规划诊断**，最多两次真实请求、不调用工具、不重跑目标、不写原 run：原目标生成 GoalSpec；将**原混杂 GoalSpec**送入改提示后的 Planner。使用简化公开项目上下文，**不是同上下文 A/B 对照**。共输入 5,997 / 输出 6,429 tokens，独立记账，不能加进或改写原 35 次调用。

- Planner 返回的必需产物为 database、两份文档、新测试，没有带注释路径，也没有强制可选辅助模块。
- GoalSpec 虽不再拼注释，仍把可选辅助模块等允许路径列进 target_outputs；**该层语义仍不稳定**。Planner 这次抵御了混杂输入，但不能宣称两层均已治愈，更不能称端到端修复验收通过。

## 工程验证与后续

Windows 相关 114 / WSL 相关 114 项通过；Ruff 通过，mypy ratchet 零新增（保留 60 既有错误，不更新 baseline）。Windows 完整 **1738 passed / 3 skipped / 42 deselected**（497.16 秒），离线 benchmarks 全过。提示修正提交 `f5fd28d` 的 [Verify 43002254995](https://github.com/z243802480/mult_agent_code/actions/runs/43002254995) 三 job 全绿（Python 3.11、3.13、Studio），已核实精确 head SHA。后续文档回执不改变产品代码；该 Verify 不包含 keyed 真模型证明。

下一项收敛条件产物与允许范围的规划语义：保留以上失败，先登记新目标与独立检查，再用新的普通会话验证；不要复跑本目标或把未执行的 counts 阶段补成通过。保留通用 prompt/结构化契约方向，不添加文件名/语言/provider 补丁。小时级连续运行、独立 provider、keyed CI 证明仍未完成，keyed proof 仍 NOT RUN。
