# S107 任务契约传递与完整目标自主解题

状态：第四轮独立闭环验收通过；前三轮失败保留。本刀证明一个完整多模块目标可在既有边界内自主交付，不证明所有一到三小时任务可靠。用户关心目标下持续自主解题，不要求固定运行时长。

## 结果

最终冻结代码与 main@7e0055c 的 249 个生产 Python 文件在统一换行后逐项相同。WSL Ubuntu / Python 3.12，普通 goal、auto、no-research、max-iterations=32，默认 200 模型调用 / 1000 工具等预算，外部单次上限 3600 秒。实际 438.16 秒（7 分 18 秒），提前完成，无超时。

- 模型自行规划并完成四任务：存储/格式、HTTP、CLI、最终整合验证。
- 完整目标运行后，外部独立重跑不可变原测试：53/53；运行前固定且未提供给模型的 oracle：PASS。
- Review pass / 1.00，Accept accepted；无后续任务、无待决审批。
- 44 次调用均 MiniMax-M2.7，输入 1360929 / 输出 39446 token；134 次工具调用、6 次失败，1 次协议纠正、1 次 compact、0 次 goal replan。
- 运行内解答修改、人工拆题、额外纠错提示均 0。外部驱动仅提交完整目标、独立验收、调用标准 Review/Accept。
- 只修改 boardkit 下六个 Python 文件；测试/需求等四个非实现输入逐字节不变；无范围外源码变化。工具失败包括补丁格式/上下文错误及一个标题大小写假设错误的探索脚本；保留红证据，没有把它们说成全部已重跑变绿。必需阶段检查和最终完整检查均实际通过。

工具错误后模型继续推进、压缩后能完成全部任务，这些已有证据。当前样本仅七分钟；没有验证真实一到三小时的上下文持续性、长时间 provider 波动或预算消耗。输入 token 总量也提示成本尚需实测，不能以一次成功宣称稳定降本或对标能力持平。

## 任务与独立验收

输入：benchmarks/dogfood/boardkit_goal/，标准库本地任务板骨架。要求持久化 CRUD、乐观并发控制、评论、幂等、原子快照导入导出、CSV、localhost HTTP 和 CLI。原始 53 项测试冻结，骨架基线 40 failed / 13 errors。

独立 oracle 原样副本：benchmarks/dogfood/boardkit_oracle.py.txt。它在运行前确定，未复制到模型工作区，也未随结果改断言。覆盖 65 条记录状态机、组合过滤/分页、过期版本、评论、删除、无效导入原子性、快照往返、16 路幂等创建和 CSV。

oracle SHA256：efe0167535ed54f76e6e23fae7af42304312f00eb42cdf0a4d6eea4e9affe8dd。

## 已观察到的卡点与工程修复

1. PlannerAgent 输出与归一化贯通 read_scope / validation_commands，提示每任务检查在自身及依赖完成后即可通过，完整目标验收留到整合阶段。只读依赖不赋写权，PathGuard 仍保护敏感路径，GoalSpec 不改；旧格式保持回退。
2. 只读 verification 重规划保留 readonly、空写范围及原验收命令，提示对照用户规格诊断自建断言。实际实现缺陷不会自动获得写权。
3. 模型显式声明的阶段命令标记 command_source=planner_task（两份 schema 同步）。完成契约消费这些必需命令的实际证据；缺失/写后过期检查经既有工具网关及审批门执行。必需红或缺失仍失败；探索性红继续回灌并留账，避免未实现的下游测试自动绑死中间任务。旧计划规则不变，重规划保留命令和来源。没有按题目、模型或错误文本过滤。
4. ShellGuard 将 format 从任意词命中改为实际命令位置，普通打印不再误判；format/format.exe 磁盘命令、Format-Volume、包装和解释器危险形式仍拒绝。
5. run 恢复轮次在任务完成后清零，衡量连续未推进的循环；连续失败仍停，单任务修复/重规划及全局预算不变。

这些均为由失败样本指向的通用接线/边界修复；没有给 BoardKit 写答案，没有默改 shell 命令，没有放宽持久化 schema 或高危操作审批。未新增编排 Wave、维护命令或默认并发写。原生工具消息/流式通道未在本刀翻默认。

## 四轮记录

每轮相同需求、骨架、原测试和 oracle；独立工作区与冻结代码。轮间修改 harness 属研发介入，不能把四轮拼成一次零介入成功，也不能用它们统计稳定成功率。

| 轮次 / WSL 缓存目录 | 时长 / 实际模型调用 | 独立验收 | 停止事实 |
| --- | --- | --- | --- |
| 首轮 / asteria-s107 | 627.56 秒 / 76 次 MiniMax | 53/53、oracle PASS | 自建脚本把 Task/task 当相同幂等负载，违背 trim-only 标题规格；只读重规划变写任务卡 brief gate，paused，未 Accept |
| 第二轮 / asteria-s107-retry | 650.73 秒 / 69 次 MiniMax | 原测试 FAIL、oracle FAIL | 中间任务提前跑全套，未实现 HTTP/CLI 的失败被升格；修复丢阶段命令。本方正常 pause 一次，未修改解答/追加提示 |
| 第三轮 / asteria-s107-contract | 206.17 秒 / 34 次 MiniMax | 原测试 FAIL、oracle PASS | 仅存储/格式完成；打印 format 被误判格式化，pending approval，未批准/未 Accept |
| 第四轮 / asteria-s107-final | 438.16 秒 / 44 次 MiniMax | 53/53、oracle PASS | completed，Review 1.00→accepted；运行内解答介入 0 |

首轮 178 工具 / 7 失败、4 次协议纠正、2 次重规划、1 次压缩，输入 2139074 / 输出 46523 token；第二轮 208 工具 / 32 失败、4 次协议纠正、2 次重规划、1 次压缩，输入 2020293 / 输出 46883；第三轮 79 工具 / 2 失败、2 次协议纠正、0 次重规划、1 次压缩，输入 928122 / 输出 28854。原输入和范围保持。首轮冻结代码 d35faaf 的 Verify 42797634051 三 job 全绿，但其目标仍失败；CI 与目标验收分别记账。

每个缓存根目录均保存 code-frozen/、board-workspace/、goal.txt、before-hashes.json、goal-process.json、result.json、运行及独立验收日志；run_id 均 run-20261110-0001，需带完整工作区区分。最终根目录还有 production-hashes.json。外部驱动/oracle 位于 Windows 用户临时目录 asteria-s107-board-*.py。运行冻结副本不跟随仓库后续编辑。

本次进程临时禁用未配置的 strong/cheap，正常读取既有 medium 路由；以 model_calls.jsonl 核实四轮全部实际调用为 MiniMax，而非仅看初始化路由告警。凭据未输出或迁移，未入库。

## 工程验收与下一步

追加前全套 Python 1563 passed / 3 skipped / 42 deselected；追加后规划/执行/重规划/run/安全/文档及新契约定向 247 passed（164.48 秒）。Ruff src/tests/benchmarks 通过，mypy 棘轮无新增（60 项既有债）。main@7e0055c 的 [Verify 42804939681](https://github.com/z243802480/mult_agent_code/actions/runs/42804939681)：Python 3.11/3.13、Studio 三 job 全部 success（浏览器 UI 真执行）。

ACTIVE_SLICE=S107，本刀已收口，保留当前索引供下一刀交接。下一优先项是从真实仓库工作中选择更复杂的完整目标，明确验收与预算后测试更长的自主推进；不人为等待或重复测试凑一小时。独立 provider 仍受额度限制，不冒充通过。S106 整体失败与 fake 混路由历史结论不改；既有未跟踪验证目录、本地路由/凭据继续排除于提交。
