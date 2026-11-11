# S127：验证范围与命令副作用

2026-11-12；[brief](../../../benchmarks/reference_briefs/S127-verification-scope-convergence.md)。与 S128 同批实现，执行器 `49602ba`；`da85a58` 只修正预算测试夹具，src/schemas 不变。

## 实现

共享 GoalSpec/Planner/AgentHarness 指导区分用户必需命令、产物验证和可选诊断。规划前确认检查是否适用，不能无依据把全文/全仓探针升为必过；旧失败须对比原基线并报告，新声明独立执行。不得改 runner、过滤错误造绿，验证操作也须考虑写文件副作用与授权隔离，有证据覆盖后不重复无目标的诊断。认知与验证方法选择仍归模型，没有按模型、任务、文件名猜修复或加严 JSON。

RunCommand/RunTests 使用已有有界 stat 扫描，反馈实际 created/modified/deleted 路径；扫描不可用时明确 unknown。错误、超时后的变化也保留，不自动删除，不读文件内容。摘要只报告 shell 退出状态，不把任意脚本、管道末端0称为测试通过。`ok` 仍是原退出码契约，stdout/stderr 和权限门保持。

参考 [Anthropic 长任务环境管理](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)与 [harness 简化经验](https://www.anthropic.com/research/harness-design-long-running-apps)，复用工程事实与提示通道，不加修复状态机。stat 扫描有原5000文件上限、忽略运行/缓存目录，不是内容哈希或 OS 强隔离承诺。

## 联合验收

与 [S128 报告](S128-interruption-accounting-recovery-20261112.md)共用一次新目标：从正式接受 S124 源码另复制，在 usage 增加 Put counts example，替换已有文档并新增缺失文档，展示计数和其它文档保持。没有采用 S126 失败产物，也不是重跑 remove 目标。要求自包含 doctest 和原完整 pytest，验证后按公开目标加载 retrospect；该技能不是自发选择证明。

输入/检查器/执行器提交后冻结，实际 Runtime 环境预检：基线缺小节为红，原271 tests过，正控制绿；纯文本和错误输出负控制失败、正确输出正控制通过。检查器不进模型工作区，默认 session_agent/原权限预算、900秒外部上限，一个目标，无中途提示/人工产物编辑。

**联合目标拒收，正式 Review/Accept NOT RUN。** 实际449.44秒，42条完成模型记录均MiniMax-M2.7；输入1,147,339/输出23,832 tokens与原汇总精确对应。80本地+4技能=84唯一对应观察，其中一条删除补丁在registry前被拒、未计预算，故实际计数83、预算单位68，分类也逐项对应。不是费用漏计。MCP未实跑，不外推小时级、独立provider或成对因果效果。

新示例整节12次/0失败、API4/0、空上下文隔离7/0（重复核验同组新语句）；项目271 passed/1 skipped。模型自行修复了最初漏写的insert_multiple返回值，最后diff只插入目标小节，旧内容和其它原文件哈希保持。原输入与冻结执行器未改。

Planner 已将检查缩到新小节，但自拟单行Python方法有SyntaxError；独立compile已证，不是示例语义失败。模型给出并执行了可用的多行等价检查，可原声明的错误命令在两代重规划中仍被保留为必过方法。另一次改写的提取器错误地执行了旧示例，返回72，并创建db.json/db1.json/db2.json；**新增stat观察当场如实报告这三条创建**。模型随后发现并尝试清理：删除补丁被作用域拒绝，shell unlink触发常开高危guard，运行正常paused/DECISION、保留pending审批；未到外部上限，控制器没有终止它，也没有批准删除或人工清理。

所以S127的观察/指导已交付，但“自主验证会收敛”的整体目标未验收。不能把CLI返回0、可用替代脚本或示例通过冒充整个目标成功。人工核对80条本地输入和8次补丁，除已披露副产物/未执行的受限删除外，未发现秘密、网络、evaluator/执行器访问或安装；retrospect按公开目标调用3次、debug为模型自选1次，不称retrospect自发选择。

同次运行暴露修复任务丢失typed编辑上限，已另做 [S129](S129-replan-edit-boundary-20261112.md) 生产路径修复/回放，不反写这个旧样本。下一项总计划S130研究自拟方法的证据化修订：用户/项目检查与要求不能降低，模型自拟错误方法需要有失败和替代实证的可审计修订路径，不能简单升严JSON或写Python语法特判。

## 环境验证

最终三项源码e0fffc1：Windows完整1864 passed/5 skipped/42 deselected（571.71秒），Ruff(src/tests/scripts)、类型ratchet无新增（60 known）、五个离线基准通过；WSL相关分组82、最终恢复10、预算7及S129最终73通过，有交叉不相加。全目录lint的既有未跟踪验证输入仍排除在提交之外。

中途预算边界测试原夹具故意把规划费用清零、期待再获完整4次总预算；恢复修复后正确读回旧费用而提前停，导致该旧断言失败。测试改为保留相同4次执行余量，同时验证规划前缀和规划+执行总数，原危险工具不执行/产生预算决策的断言保留。没有提高产品预算。最终完整回归通过。

最终源码 [Verify43072934506](https://github.com/z243802480/mult_agent_code/actions/runs/43072934506) 的Python3.11/3.13、Studio均通过，UI步骤success；此前镜像DNS失败本次未出现，没有改workflow或跳UI。keyed nightly仍NOT RUN。

证据：WSL `~/.cache/asteria-evaluations/s127-s128-joint-20261112`，工作区 `~/.cache/asteria-workspaces/s127s128-doc-put`；S126 原失败保留。
