# S123：复杂批量目标、真实协议恢复与文档反馈修复

2026-11-11；[brief 与冻结登记](../../../benchmarks/reference_briefs/S123-complex-batch-real-proof.md)。

## 结论

**初轮自主目标未通过整体验收；外部反馈后的文档修复通过并正式接受。** 两个结果分别保留，不能合成“初轮自主成功”。本刀产品执行器仍为 `6e3be93`，工作集中于真实验证、可执行示例和恢复证据，没有仓库/模型特判。

初轮 521.52 秒（约 8 分 42 秒），完成实现、测试、文档和验证四个任务；固定 API oracle **14/14**、旧 readonly **20/20**、项目 **271 passed / 1 skipped**（原 236 + 新 35）以及范围/源码绑定检查均过。自然触发一次 GoalSpec 有界纠正，最终分类和 canonical 投影正确。但 usage 中两次 put 的示例把 inserted 写成 1，人工审计与实际 doctest 确认错误，故拒收。

隔离默认 Review 未识别该问题。随后另开**外部反馈诊断**：只把真实示例失败与公开执行检查交给普通 harness，在独立源码副本的新 run 中修文档；70.09 秒、14 次模型调用，只改两份文档。两个文档的 **10 个示例检查全过**、项目 271 tests 不变；正式 Review 1.00→Accept accepted。原初轮代码、文档、运行状态和账本字节未改。

## 更复杂的目标与预检

目标为 `TinyDB.apply_batch(operations, *, dry_run=False)`：全量预验证、逐项快照、跨表顺序 put/remove、操作计数、深隔离、有效批次一次读/至多一次写、只读拒绝与 dry-run、异常传播、成功后的已有句柄查询/下一 ID 刷新、失败/不写时缓存保持、JSON/custom storage。不是 S120 快照重跑。

输入为 S113 已接受 readonly 源码产物（MIT），复制不带 `.asteria`/缓存；不使用 S120/S121 未接受解法。执行器从 `6e3be93260d24beca2d27c4af02b48d30b52625a` 仅导出 src/schemas，完整产品基线 Windows 1756 / WSL 相关 106、精确 Verify 43008738110 绿。

公开 pytest、绑定、旧 oracle 先经真实 RunCommandTool（ShellGuard、环境净化、进程围栏）在 Runtime 相同父环境通过，导入显式声明 `pythonpath=.`，没有控制器额外项目 PYTHONPATH。新 API 基线红；14 方法 evaluator-only 正控制绿、过量写入反例被拒绝。控制实现未写模型工作区或作为提示。独立 oracle 使用公共 API 和 evaluator 自有 storage，不要求私有布局。

首次调用前提交 `b4b48a7`，冻结全部输入/执行器哈希，实际 native harness/high_risk，不强制档位；一个初轮目标，外部上限 1800 秒未触发，运行时预算/权限未提高，没有中途解题提示、代修、人工暂停或时间填充。

## 初轮真实过程

- 72 次真实 MiniMax-M2.7 调用，输入 **2,655,313** / 输出 **52,347** tokens，逐项与 cost_report 相符，within_budget。
- GoalSpec 两次调用均传输 success，输出分别 4000、2501 tokens，第二次后得到有效 typed 提案。固定实现仅在收到无效提案时发一次纠正，后续没有重规划或新的 GoalSpec，因此确认该分支自然触发。未保存首次具体解析/schema 错误文本，不断言“4000 tokens 就一定是截断”。
- 四个 required、两个 allowed、一个 optional 标签及 canonical 产物正确。实际仅改 tinydb/database.py、docs/usage.rst、docs/api.rst，新增 tests/test_apply_batch_s123.py；其余源码/旧测试/公约/配置、原 S113 与冻结执行器哈希未变。
- 173 条已记账工具记录与 173 条观察同 ID、唯一；98 read_file、12 todo_write、12 search_text、17 run_command、13 apply_patch、12 run_tests、1 todo_read、2 write_file、2 diff_workspace、1 remember、2 list_files、1 find_files。
- 工具记录 3 denied / 9 failure：范围拒绝为 tests 检索一次、测试阶段 storages.py 读取两次；失败包括四次 patch 形式、一次 patch 上下文、一次自建 storage 调用、一次新增测试（6 项失败）及两次 diff 调用。模型继续使用已允许的源码/测试信息，未申请放行，没有自动 replan。
- 35 项新测试最初有错误计数、缓存/输入断言，模型修正了测试；最终独立公共行为检查另外确认 API，旧测试未改。实现、测试、文档、最终验证 4/4 done；remember 一次记录了公约摘要。

人工检查所有记录的路径/命令、13 次 patch 目标、实际来源 diff、两份文档和 400 行新增测试，未发现答案/执行器或安装包源码/其它实验/秘密/网络访问。自写测试含私有缓存断言，接受不能仅凭其绿色；独立公共 oracle 是另一个信号。

## 文档拒收与评审诊断

新增 usage 示例依次 put ID 1、remove ID 1、put ID 2，按公约应 inserted=2 / removed=1，但文档写 inserted=1。标准库 doctest 在真实工具环境执行该新增节，**5 次尝试、1 次失败**，确认人工发现。该执行检查是后续诊断，不改写原冻结 API oracle 或其通过结果。

因此原初轮最终 `independent_accepted=false`，没有正式 Review/Accept。native completed/ACCEPTED 是运行时原始结论，不替代独立拒收。

在源码和运行状态的隔离副本上调用一次默认 Review，未向模型提供 doctest 失败、错误位置或答案。它新增 1 次真实模型调用，仍返回 pass/1.00、理由为“五条验证命令通过”；没有识别错误。未调用 Accept，原初轮完整哈希不变。这个诊断说明既有声明命令与默认评审未覆盖文档实例，不能把测试通过率当作全部内容的保证。并非由本次证据断言所有模型评审都无效。

## 外部反馈阶段（新 run，单独记账）

调用前提交 `5752273`：公开标准库 doctest 检查器与反馈目标另行冻结，基线示例红、原 271 tests 绿。从初轮 SOURCE 复制不带 `.asteria` 的新工作区，不迁移 run/profile；默认实际为 session_agent。给出真实 Expected/Got，不提供补丁，要求修 usage 并给 API 节补自包含可执行示例。只允许两份文档变化，代码/测试/检查器均不改。

结果：70.09 秒、14 次模型，输入 333,356 / 输出 7,464 tokens；只把错误示例修正并补 API 示例，未通过改实现迁就文档。10 个示例全过，项目仍 271 passed / 1 skipped。人工检查 28 条工具路径/命令与两份文档 diff 后，正式 Review 1.00→Accept accepted；该评审为 deterministic-first，新增模型 0。账本前缀、源码/检查器哈希与最终计量保持。

原 72 次、隔离 Review 1 次、反馈修复 14 次，合计 **87 次模型调用**，未重置原 run 账本；诊断合计限制 200 次、文档修复外部上限 600 秒，原初轮 1800 秒不改，也不合并耗时制造“长任务”证明。这是外部反馈辅助修复，不能称同 run 恢复或初轮无干预成功。

## 证据、工程验证与后续

WSL 初轮：`~/.cache/asteria-workspaces/s123-tinydb-batch`；审计：`~/.cache/asteria-evaluations/s123-complex-batch-20261111`，包含原 final-result（拒收）、doctest、隔离 Review 及其副本。反馈源码：`~/.cache/asteria-workspaces/s123-doc-feedback`；审计子目录 `doc-feedback` 有单列的 accepted 结果。两 run 都是各自新建的 run-20261111-0001，不能因同名而混淆。

判分器/文档/示例检查新增回归 Windows **35** / WSL **35** 过，Ruff 过；产品 src/schemas 与 6e3be93 一致，复用原完整基线。主登记 `b4b48a7` 的 [Verify 43028215001](https://github.com/z243802480/mult_agent_code/actions/runs/43028215001) 三 job 全绿；反馈登记 `5752273` 的 [Verify 43032903506](https://github.com/z243802480/mult_agent_code/actions/runs/43032903506) **失败**：Python 3.11/3.13 通过；Studio 的 lint/format/typecheck/unit/smokes 通过，但浏览器系统依赖安装报 `Temporary failure resolving azure.archive.ubuntu.com`，UI 测试 skipped。根据公开 failure annotation 确认，不把依赖故障记为产品通过；完整日志 API 无权限（403），未绕过鉴权。

下一项 S124：将可执行文档示例及其声明输出纳入常规验证规划，明确命令通过率与产物验证范围，利用实际工具证据反馈模型；不加 TinyDB/模型/错误词特判，不靠更严 JSON 门禁或再问一个模型替代执行。本轮已自然证明一次 GoalSpec 纠正与外部反馈修复；小时级、多 provider 连续自主可靠性仍未证明，keyed proof 仍 NOT RUN。
