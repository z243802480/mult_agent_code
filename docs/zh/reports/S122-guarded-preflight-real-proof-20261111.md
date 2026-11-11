# S122：实际工具环境预检与新链路真实验收

2026-11-11；[执行 brief](../../../benchmarks/reference_briefs/S122-guarded-preflight-real-proof.md)。

## 结论

**独立检查与正式 Review→Accept 均通过。** 新 partition_items 目标执行 208.50 秒，固定公开行为 oracle 12/12、旧 API oracle 15/15、项目 273 tests 全过；产物意图分类、canonical 投影、规划、严格编辑范围、真实声明命令与源码绑定均通过。人工审计后，正式 Review pass / 1.00→Accept accepted。

本刀复用产品执行器 `6e3be93`，改动集中于实际环境预检、冻结验证资产与证据文档。没有为某仓库/模型修改运行时。S120、S121 的拒收和未运行阶段原样保留，本结果不替换旧失败。

## 先预检再调用

- 起点为 S116 已接受的 cachetools 源码产物（MIT），复制不带旧 `.asteria`/缓存；不使用 S121 的未接受产物，不是干净上游重新解题。
- 执行器仅从 `6e3be93260d24beca2d27c4af02b48d30b52625a` 导出 src/schemas，精确 [Verify 43008738110](https://github.com/z243802480/mult_agent_code/actions/runs/43008738110) 三 job 全绿；产品完整基线 Windows 1756 / WSL 相关 106。
- 所有预检和独立命令使用真实 RunCommandTool，经过 ShellGuard、环境净化和进程围栏；工作目录与实际 Runtime 相同，父 PYTHONPATH 仅指执行器 src。公开 pytest 显式使用 `-o pythonpath=src`，绑定/外部 oracle 显式引导项目源码，没有用控制器环境覆盖掩盖导入条件。
- 首次模型调用前，原 264 tests、绑定、旧 oracle 全绿，新 API 基线红；12 方法正控制绿，错误分组反例被拒绝。控制实现只在隔离检查进程临时定义，未写模型工作区或作为解题提示。
- resolver 实际为 native **harness/high_risk**，提前记录并沿用，没有强制 session_agent 或迁移 profile。此预检验证真实命令工具，不声称完整 task gateway 重放；任务期另审实际 gateway 记录。
- 目标、公约、检查器哈希登记在 brief，调用前提交 `e05186e`。冻结后只执行一个新目标，1800 秒外部上限未触发，预算未增加，没有人工源码代修、导航提示、暂停或时间填充。

## 实际结果

| 项目 | 结果 |
| --- | --- |
| GoalSpec | 一次真实调用即有效，输出 3764 tokens；没有 fallback |
| 意图与投影 | 四个 required、keys.py 为 allowed、_partition.py 为 optional；条件分字段，canonical 只含四个必需字面路径 |
| 实际计划 | 实现→测试/文档→验证，3/3 done；产物全部位于允许集合 |
| 必需文件 | 修改 src/cachetools/__init__.py、docs/index.rst；新增 docs/分组（只读）.rst、tests/test_partition_items_s122.py |
| 范围/旧行为 | 没有其它文件变更，原测试/配置/公约保留；仅许可与可选文件均未被强制修改或创建 |
| 独立功能 | partition 12/12、旧 peek 15/15，公开同身份 pytest 273 passed（原 264 + 新 9） |
| 源绑定 | 公开绑定命令指向本工作区 src/cachetools；源 S116 与冻结执行器哈希不变 |
| 正式评审 | Review pass / 1.00；Accept accepted / completed，review_status=pass |

执行阶段 33 次真实 MiniMax-M2.7 调用，输入 1,112,684 / 输出 19,561 tokens。正式 Review 又调用一次真实模型；最终 34 次，输入 **1,208,252** / 输出 **22,540**，与最终 cost_report 逐项相符。评审、接受没有重置预算或改写先前账本；既有 model/tool/observation 字节前缀保留，工作区源码哈希保持。正式 Review 分数理由中的“7 verification commands”是验证记录口径，不等同于 273 个测试用例。

74 条工具记录与 74 条观察同 ID、唯一：44 read_file、8 todo_write、1 search_text、7 apply_patch、6 run_tests、3 run_command、2 write_file、3 list_files。0 denied、4 failure：两次 patch 形式无效、两次新增测试失败；模型在原执行循环内自行恢复，0 自动 replan。最终实现没有为错误测试改变行为，独立 oracle 另外验证两边分组、顺序、身份、单次回调、异常、回调变更、淘汰和过期存储。

人工审阅全部记录的路径/命令、7 次 patch 目标、可信来源 diff、文档与新增测试，未发现外部答案、执行器/安装包实现、其它实验、秘密或网络访问。新增测试中有私有过期容器与 pair 身份断言，属于质量局限；本次接受依据独立公开行为检查，不将这些更强断言升为 API 要求。没有运行或声称 Sphinx 构建。

## 证据与验证边界

原始证据在 WSL `~/.cache/asteria-evaluations/s122-guarded-proof-20261111`，包含实际工具预检、冻结输入、独立检查、manual-audit、formal-review/accept 与 final-result。目标在 `~/.cache/asteria-workspaces/s122-cache-partition`，run `run-20261111-0001`。未把隐藏检查器、控制器、旧解法或执行器源码放入目标工作区。

新增判分器/文档回归 Windows **30** / WSL **30** 通过，Ruff 通过；冻结登记提交 `e05186e` 的 [Verify 43010445336](https://github.com/z243802480/mult_agent_code/actions/runs/43010445336) Python 3.11、3.13、Studio 三 job 全绿。产品 src/schemas 与已验证的 6e3be93 相同，故复用其完整基线；本机没有重复宣称运行新的完整 1763 项。

本轮证明了实际环境一致时 typed 意图→规划→执行→独立检查→正式接受的一次闭环。**GoalSpec 一次有界格式纠正没有触发**，仍只有确定性回归证明，不能声称真实恢复也已验证；S119 的重验恢复未在本轮触发。约三分半钟、一个 provider 的样本不证明小时级或多 provider 稳定性，keyed proof 仍 NOT RUN。

下一项在同一主路径选更复杂的真实工作负载，继续审计自主恢复和测试断言是否偏离用户目标；先核对实际环境/档位，再登记需求与独立验收。任务按完成条件推进，不靠增加预算、人工制造失败或填时间来撑长。
