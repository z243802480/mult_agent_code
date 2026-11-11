# S117 — 自然追加需求与续作边界纠偏

2026-11-11。工程修复已落地；真实追加功能和累计账本通过，但本轮严格独立验收未通过，未为新需求执行正式 Review/Accept。原因是质量门改写了旧任务的备注与时间，不改验收条件、不回写旧记录或重跑样本掩盖失败。

## 预注册与来源

- 入口为总计划 §16.2 第 29 项；brief：`benchmarks/reference_briefs/S117-natural-session-follow-up.md`。
- 执行器冻结为 `808a9e6`，仅导出 src/schemas；已包含 S116 的空读取范围/拒绝记账修复及本刀首个续作读取范围修复。
- 在 S116 已接受的 cachetools v6.2.1 工作区副本上追加 `peekmany(keys[, default])`，原工作区不动。这是有历史产物的自然续作，不能称新的从零独立解题。上游仍为 MIT、commit `ca7508fd56103a1b6d6f17c8e93e36c60b44ca25`。
- 公开公约 `benchmarks/dogfood/cachetools_peekmany_contract.md` SHA256 `dd3312eebf3ef6e24637af30281d47a7065ceabbb3a1ef08e41a3f2fe9967edd`；外部 oracle `cachetools_peekmany_oracle.py.txt` SHA256 `019d5c21724d6dc0eb36fe6c33a898d02900346dcda17ac093b0116b23981261`；目标文本 SHA256 `335505adb88e837d62e7a528ee6bdb74202b47db7f1fc9c8ece6a15540e747f8`。均在模型调用前落盘。
- 调用前新 oracle 12 方法因缺 API 出现 53 个 subtest ERROR，旧 oracle 15/15、原有测试 264 过。检查器另有 8 个合法表示/坏身份、重复丢失、计时过量和过期清理反例回归，不假设被测对象的私有布局。

选择 API、公开行为和边界后让模型自己读文件、实现、调试；未指定导航工具、未给解题提示、未人为暂停、未增加预算。既有普通 `goal --continue-session` 复用 `run-20261111-0001`，追加 task-0002，跳过新的 GoalSpec/Plan。

## 实际结果

执行 314.50 秒，新 oracle 12/12、旧 oracle 15/15、全部测试 **308 passed**（原 264 + 新 44），来源绑定、允许改动范围、执行器哈希和原工作区哈希通过。只改 `src/cachetools/__init__.py`、`docs/index.rst`，新增 `tests/test_peekmany_s117.py`；原测试、配置、许可证和两份公开公约未改。

新增 34 次真实模型调用（33 执行 + 1 收尾），全部 MiniMax-M2.7；累计从 24 到 58。新增输入/输出 token 为 1,412,279 / 19,805；累计 2,167,780 / 37,822，与模型账本及 cost_report 精确对齐，within_budget。工具累计从 43 到 153，原模型/工具/观察/events 账本字节前缀均保持。无新增 GoalSpec/Plan、重规划或控制器解题介入；一次 context_compacted 是结尾正常 handoff，不能当成压力压缩实证。

模型曾误覆盖文档，随后从自身工具备份恢复原文并追加说明；一次新增测试调用 11 failed / 28 passed，其中 10 条缺 timed-cache 构造参数，1 条错误地用过期成员查询断言存储。模型自行修正。其新测试含一条私有 TTL links 断言及一个对访问副作用不敏感的 LRU 场景；独立 oracle 另用公开 expire 和无频率平局的淘汰反例验证，不把自建测试绿等同独立验收。Sphinx 未安装，未声称文档构建通过。

新增 110 调用与 110 观察一一对应，串行 ID 无重用；0 denied、1 执行失败。工具为 read_file 73、search_text 11、run_tests 9、apply_patch 6、todo_write 4、list_files 3、run_command 2、write_file 2。人工解析全部输入、检查命令/补丁/源码/文档/新增测试，未见外部答案、运行时源码或安装包实现读取；读取自身 `.asteria/backups` 恢复文档属于本次工作产物。

首次真实观察到读取反馈：73 次 read_file 均成功，payload 均不超过 6000 字符；56 次出现 next_offset，按“下一次同路径读取”口径有 2 次使用该 offset（测试文件 190、源码 594）；partial_line 未触发。该计数仅证明本轮发生和采用，不能证明所有导航高效或存在因果收益。0 denied 也不能替代拒绝路径的确定性测试。73 次读取及重复回看值得后续量化，当前不按模型名/能力打策略补丁。

## 严格验收失败与工程修复

旧 task-0001 的 notes 被追加 `Auto-revised by task plan quality gate: missing_acceptance, missing_artifact.`，updated_at 从 13:39:13 变为 14:31:08。其余旧任务字段保持，但预注册要求整个旧任务保持不变，因此 `source_qualified=false`、`independent_accepted=false` 保留。新增 task 还被回填了旧 peek/peekitems 的 acceptance/artifact，并继承旧 verification_policy。最终 summary 的 review_status=pass 也来自上阶段仍在活跃路径的 eval_report。

原生 runtime 按既有 auto 权限和本轮可执行验证自动标为 ACCEPTED；这属于已授权的 auto-finalize，不能代替本轮独立接受或新正式 Review。我们未手改原运行阶段、旧报告、任务或失败结果；没有为新需求另外执行正式 Review/Accept。

修复均为通用生命周期/证据管理：

1. `808a9e6`：续作 read_scope=[] 与冷 session 一致，保留 PathGuard 和原写门。`context/spec.rst` 确定性 1 红 2 绿→通过，秘密/越界和额外写仍拒绝。
2. `4048d19`：追加任务以本次用户指令为 acceptance，使用既有通用产物占位，不猜解法或文件；清除旧验证元数据。质量门只修非终态任务，不改写/重新激活 done/discarded，仍保留对历史任务的合法依赖。新回归 5 红 5 绿→通过。
3. `0d0f5f1`：新任务启动前，把旧 eval/review/final 报告原字节归档至 `continuations/<新 task id>/`，活跃记忆 review 重置 unknown。新正式 Review 可正常写回活跃报告。回归先红后绿，不改 auto-accept 默认、不删历史账本。

在最终执行器上另做**无模型**的真实历史夹具回放：仅调用 prepare + quality，旧任务/原成本与账本不变，新 criterion 对应追加指令、无旧验证残留、旧 Review 原字节归档且活跃 Review 缺席；质量分 warn/0.976。该确定性回放不改原实验，也不是第二次模型成功样本。

## 验证与本机证据

首版 Windows 全套 1692 过；4048d19 的 Windows 全套 1697 过、3 skipped、42 deselected。最终报告归档改动的 Windows 相关 **97 过**；0d0f5f1 的 [Verify 42975350372](https://github.com/z243802480/mult_agent_code/actions/runs/42975350372) 三 job（Python 3.11/3.13、Studio）全绿，覆盖最终代码完整 Linux 检查；Ruff 与类型棘轮无新增错误（60 项既有基线），WSL 最终相关 25 过。初次 808a9e6 的 Verify 42972761639 三 job 已绿，不能替代最终代码的 CI。

本机目标为 `~/.cache/asteria-workspaces/s117-cachetools-follow-up`，外部证据为 `~/.cache/asteria-evaluations/s117-follow-up-20261111`：`registration.json`、`pre-review-result.json`、`result.json`、`manual-input-audit.json`、`read-hints.json`、原账本前缀、哈希清单、独立检查日志及两份分离的确定性 replay。原 S116 工作区仍不变。

下一步：为修复后的完整续作生命周期预注册另一个自然需求，验证新旧任务/判据/Review 新鲜性和累计预算，按新目标取样；不重跑本题改变结论。读取冗余先测量再决定是否需要通用上下文调整。单次五分钟不证明一到三小时可靠性；独立 provider 仍未验收，GitHub keyed Studio/ring proof 仍 NOT RUN，不作为研发前置。
