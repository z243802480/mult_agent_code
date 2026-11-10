# S107 任务契约传递与完整目标自主解题

状态：前三轮调试样本均未闭环成功；修复已观察到的通用卡点后，第四轮从相同骨架完整重跑 RUNNING。用户关注目标下持续自主解题，不要求固定运行时长。

## 已完成的工程修复

PlannerAgent 的任务输出加入 read_scope / validation_commands；归一化保留模型声明的只读上下文及局部验证，不再只从产物反推读范围或总是复制全局验证策略。缺省旧格式仍按原方式工作。原任务指导及产物路径保留，只读依赖不加入 write_scope，PathGuard 的保护路径规则继续生效。

提示要求模型让每任务检查在该任务及依赖完成后即可通过，把完整目标验收放在实现之后；不按题目硬改任务图或命令。模型仍可能规划不佳，所以这不是正确性保证；GoalSpec 没有删除全局验收，目标是否完成另由独立整套检查判定。

本地规划/执行/重规划/profile 回归 108 passed；新增契约测试覆盖实际 task schema 存储往返、runtime context 传递、只读路径不赋写权限、保护路径仍拒绝和旧计划回退。Ruff 通过，mypy 棘轮无新增错误。

## 完整目标实跑

输入存于 benchmarks/dogfood/boardkit_goal/：依赖标准库的本地任务板骨架，要求完整持久化 CRUD、乐观并发控制、评论、幂等、原子快照导入导出、CSV、localhost HTTP 和 CLI。原始 53 项验收冻结，初始 40 failed / 13 errors。另用 65 条记录的状态机、组合过滤/分页、过期版本、评论、删除、无效导入原子性、快照往返、16 路幂等创建和 CSV 独立检查需求。

独立 oracle 的原样副本存于 benchmarks/dogfood/boardkit_oracle.py.txt，在目标运行开始前已确定，未复制到模型工作区；不随运行结果改断言。

WSL Ubuntu / Python 3.12，隔离工作区 ~/.cache/asteria-s107/board-workspace，run-20261110-0001。代码冻结在 ~/.cache/asteria-s107/code-frozen（基线 a8807fd 加本刀两个生产模块修改），运行时不跟随仓库后续编辑。完整目标文本、冻结输入哈希、进程起点分别为 goal.txt / before-hashes.json / goal-process.json。外部驱动及 oracle 位于 Windows 用户临时目录 asteria-s107-board-*.py。

本次进程临时关闭未配置的 strong/cheap 档，回退既有 medium / MiniMax；路由探针确认没有 fake，未迁移或输出凭据。普通 goal / auto / no-research / max-iterations=32，最多 3600 秒，默认预算 200 model calls / 1000 tools 等保持。完成可提前停止，不凑时间。运行期间不手改解答、不替模型拆题或追加纠错提示；遇安全/预算边界如实停下。

初始观察：模型自行规划六任务，已读规范；存储、格式、HTTP、CLI 及最终集成分别拿到所需 README/源码/测试读范围和阶段命令，最终任务保留完整 tests/ 检查。该观察证明接线可达，不证明目标已经成功。

## 交接

ACTIVE_SLICE=S107。待运行结束后核对 result.json、独立原测试及 oracle、范围外变化和原哈希，统计实际问题修复、重规划/压缩/协议纠正与人工介入。只有这些通过才计自主完成；如果提前失败/停在预算边界，保留失败而不盲目重跑。

本刀不直接恢复 S106 的失配任务图；保留其暂停现场。S106 的长任务整体失败与混合 fake 路由结论不改。既有未跟踪验证目录、本机路由与凭据不入库。原生工具消息/流式通道仍不在本刀翻默认。

## 首轮完整结果及追加修复

首轮冻结代码对应 d35faaf 的两个生产模块，Verify 42797634051 的 Python 3.11/3.13、Studio 三 job 均 success。普通 goal 用时 627.56 秒，76 次模型调用均为 MiniMax-M2.7，输入 2139074 / 输出 46523 token，178 工具 / 7 失败，4 次协议纠正、2 次重规划、1 次 compact。解答人工介入 0；只改 boardkit 下 5 个 Python 文件，原测试/需求哈希保持，无范围外源码变化。外部独立 53/53 与预先固定 oracle 全通过。

Runtime 仍停在 paused，未 Review/Accept，不计零介入闭环成功。最终验证中模型自建脚本把标题 Task/task 当成同一幂等负载，违背仅 trim 标题的规格；这条脚本失败被保留是合理的，不能随手忽略。真正恢复卡点是 ReplanCommand 将源只读 verification 一律变成 implementation，空写范围因 allowed_writes 未过 delegation brief gate，模型因此失去核对自身断言的机会。

追加修复只保留任务边界：源为 verification 且无写范围时，修复仍为 verification/readonly，保留原只读范围及验收命令；提示先复现、对照用户规格区分实现缺陷与错误自建断言，不允许改实现或不可变测试。没有丢弃红证据、没有删除验收门，也没有针对标题或 BoardKit 加判断。回归覆盖验证纠正后可完成、验证继续失败仍 blocked，两者源码都不变。需要修改实现的真实缺陷仍须明确提出范围需求，未自动授予写权。

新冻结副本及相同目标完整重跑保存在 WSL ~/.cache/asteria-s107-retry/；初始源代码和 53 项验收与首轮完全相同，外部 oracle 也不改。两轮之间修改 harness 属研发介入，不能把第二轮拼接为首轮零介入通过。第二轮运行内仍不修改解答、不追加提示。待该轮结束后记录结果。

## 后续调试样本与通用修复

所有轮次使用相同原始需求、骨架、53 项不可变测试与运行前固定的独立 oracle；每轮独立工作区和冻结运行时代码。轮间修改 harness 属研发介入，不能拼接为一次成功，也不能作为稳定成功率统计。

| 轮次 / WSL 缓存目录 | 时长 / 实际模型调用 | 独立验收 | 停止事实 |
| --- | --- | --- | --- |
| 首轮 / asteria-s107 | 627.56 秒 / 76 次 MiniMax | 原测试 53/53、oracle PASS | 自建验证假设错；只读重规划错误变成写任务，paused，未 Accept |
| 第二轮 / asteria-s107-retry | 650.73 秒 / 69 次 MiniMax | 原测试 FAIL、oracle FAIL | 局部存储任务提前运行全套，未实现 HTTP/CLI 的失败被强制升格；修复丢阶段命令。本方正常 pause 一次保留，解答修改/额外提示 0 |
| 第三轮 / asteria-s107-contract | 206.17 秒 / 34 次 MiniMax | 原测试 FAIL、oracle PASS | 仅存储/格式完成；脚本打印 format 被误判为格式化命令，pending approval，未批准/未 Accept |
| 第四轮 / asteria-s107-final | RUNNING | 待独立检查 | 从初始骨架重跑；代码冻结后不跟随仓库修改，运行内解答修改/额外提示 0 |

第二轮：208 工具 / 32 失败、4 次协议纠正、2 次重规划、1 次压缩；第三轮：79 工具 / 2 失败、2 次协议纠正、0 次重规划、1 次压缩。首轮写 5 个 boardkit 文件；第二轮仅 errors/store；第三轮仅 __init__/formats/store；前三轮原输入哈希及范围均保持。具体 result.json 和进程日志留在各缓存根目录。

追加修复：

- 只读 verification 重规划保留 readonly、空写范围及原验证命令；错误断言可由模型重新核对，真实实现缺陷不自动授予写权。
- 模型显式声明的任务命令用可选 schema 字段 command_source=planner_task 标记。完成契约要求这些命令的实际结果，缺失/写后过期检查经既有工具网关和同一审批门执行；必需命令红或缺失仍失败。探索性失败继续回灌并完整留账，不自动变成中间任务验收。未标记旧计划仍按原规则。重规划保留命令和来源；不按模型名、题目或错误文本过滤。
- ShellGuard 将 format 从任意词命中改为真实命令位置，并保留磁盘 format/format.exe/Format-Volume 等危险形式拒绝；打印普通数据不再要求格式化审批。
- run 恢复计数只衡量连续未推进的循环，完成任务清零；八个真实任务可跨低恢复阈值前进，连续失败仍到阈值暂停，全局预算及单任务上限不变。

新增与相关回归覆盖必需命令失败、缺失、写后过期、旧规则兼容、高危审批、只读恢复正反例、八任务推进与连续失败停止、format 安全/危险形式。追加前全套 Python 1563 passed / 3 skipped / 42 deselected；追加后规划/执行/重规划/run/安全/文档及新契约定向 247 passed（164.48 秒）；最终 CI 待回执。当前 Ruff src/tests/benchmarks 通过，mypy 棘轮无新增（60 项既有债）。

第四轮原样 oracle SHA256：efe0167535ed54f76e6e23fae7af42304312f00eb42cdf0a4d6eea4e9affe8dd。production-hashes.json 记录冻结全部生产 Python 文件，收尾需与提交版本逐项对账。最多 3600 秒，未改默认预算，不靠等待凑时长。所有实际模型调用以 model_calls.jsonl 为准；初始化 cheap=fake 提示不代表执行使用 fake，前三轮实际调用均 MiniMax，第四轮结束再核对。
