# S108 真实仓库自主修复：工具批次结果保真

状态：两轮真实仓库目标均未自主完成；随后由本轮主代理修复已复现的产品缺陷，本地回归通过，精确提交 CI 待回执。工程修复与自主目标分别记账。

## 两轮真实目标

任务为 Asteria 自身实际生产源码中的工具批次结果保真，完整跟踪快照 1351 文件、约 10.3 MB；没有用新造产品骨架代替真实仓库。main@57f6274（生产代码同 7e0055c），不复制 .git、保护文件、未跟踪验证目录或路由/凭据。目标快照带 S108 指导/计划/brief；执行器另行冻结，目标改代码不会热改自身。

真实缺陷基线：实际 ToolExecutionGateway 正确记 read_file=true、随后 write_file 因 task.allowed_tools 拒绝；execute_tool_calls 却回传唯一 read_file=false。成功前缀丢失、错误归属错名，未执行后缀不明。成功 grep 的账本名为 canonical search_text，回传却改回 grep。

独立 oracle 9 项在运行前冻结、未提供给模型，原字节副本为 benchmarks/dogfood/tool_batch_oracle.py.txt；SHA256=2b62de7261d06446cc106cb38e3507ad64fdb36f9f10116cfef18b78206be268。基线 7 failed / 2 passed。原相关回归 46/46，证明旧测试漏了组合缺陷。

| 样本 | 用时/调用 | 行为与独立结果 | 结论 |
| --- | --- | --- | --- |
| 首轮：asteria-s108 | 650.86 秒；75 次 MiniMax；219 工具/6 失败；6 协议纠正、0 重规划、1 compact | 多次 16 轮 fuse 后从头导航，源码/原测试无改动；本方正常 pause 一次。oracle 仍 7 红；原整套 1571 passed / 4 skipped / 42 deselected | paused；未 Review/Accept，未自主交付 |
| 默认 fuse 原型：asteria-s108-continuous | 223.93 秒；17 次 MiniMax；45 工具/1 失败；0 协议纠正、3 重规划、1 compact | 规划先建只读诊断任务，validation_commands=[]；旧式完成判据保留了早期 docs 读范围拒绝与一次测试 60 秒超时。随后诊断重规划被转成空写范围 implementation，卡 brief allowed_writes；自行暂停。oracle 仍 7 红；原整套 1 failed / 1572 passed / 4 skipped / 42 deselected | paused；未 Review/Accept，未自主交付 |

首轮输入 3333823 / 输出 37627 token；原型输入 593708 / 输出 16028 token。两轮实际调用全部 MiniMax-M2.7、运行内人工解答修改/额外提示均 0，源码/原测试哈希保持，无越界。首轮有一次外部控制暂停，不能藏在“零解答介入”中。原型测试失败为 never-done 测试撞实际模型调用预算后未写进度摘要，不是原工具批次问题已解决。

两轮是研发诊断样本，不是成功率抽样。原型仅将默认 fuse 对齐既有模型预算，尚不含最终每轮预算边界、批次结果修复，不能冒充最终冻结代码实跑。没有批准安全例外，也没有在失败样本中人工写答案。

## 本轮主代理完成的产品修复

自主运行没有产出可合回补丁，因此以下代码由本轮主代理实现；这不是 harness 零介入完成原目标的证据。

- 工具网关以窄异常载荷携带真实成功前缀、失败调用、原异常及未执行后缀。循环复用网关的实际 observation，保留 canonical 名称、别名来源、文件变化与原失败类型；不重放前缀、不伪造后缀成功。返回数量不匹配时明确 outcome unknown，不能静默少结果。
- 实际 _SubagentAwareToolRunner 也按顺序保留批次结果；已有相邻专家批次仍可并发，但不能提前越过前面的本地权限拒绝。未新增并发或改变全局默认。未知专家批次异常不假装精确定位到第一个子任务。
- MCP/skill 适配器意外抛异常也留下可重载的持久化失败观察；普通返回失败与旧 stop_on_failure 默认行为保留。
- 默认单任务 fuse 对齐已有 goal 模型预算（含 active profile），避免在预算内每 16 轮清掉对话；显式短 fuse 保留。纯循环在下一模型调用及响应后的工具批次前检查实际成本压力；达到既有 hard-stop 后保留观察，停止补跑验收，经原有预算 DecisionPoint 退出，不能自动重规划耗费预算。上下文压力原有压缩/恢复路径保留。预算数值没有增加。

最终修复后，原字节独立 oracle 9/9；额外回归覆盖实际包装器、拒绝后的专家不启动、相邻专家 fan-out/顺序、canonical/别名账本一致、适配器异常持久化、短返回不冒充完整、成本压力不被更高上下文压力遮蔽。预算端到端回归验证：4 次实际计费模型调用后，最后提议的写工具和补跑验收均未执行，先前 read 仍记进度，run paused、预算决定 pending、0 replan。

旧进度摘要测试使用不会 done 的假模型，现显式设置短 fuse=3，使其只验证持久化而不依赖生产默认；另有真实 BudgetController/RunCommand 小预算集成测试验证硬闸，不靠缩短假模型掩盖原型预算问题。

## 验收与证据位置

本地完整测试 1585 passed / 3 skipped / 42 deselected（388.25 秒）；末次审查的短返回诊断与共享专家预算接线，另跑最终相关 101 passed（5.50 秒，其中 wrapper 执行 9 项冻结 oracle）。Ruff src/tests/benchmarks 通过，mypy 棘轮无新增（60 项既有债）；最终精确代码 CI 待回执。目标实跑没有在最终代码上再刷样本，不能声称最终代码已通过真实仓库自主验收。

两个缓存根目录均为 ~/.cache/asteria-s108[-continuous]/，各自的 repo-workspace、runtime-frozen、before-hashes.json、production-hashes.json、goal.txt、进程记录、result.json、原回归及独立验收日志保留。两者 run_id 相同 run-20261110-0001，引用需带完整目录。驱动与外部 oracle 在 Windows 临时目录 asteria-s108-*.py。真实测试进程导入目标 src，不把冻结执行器的测试绿算目标通过；密钥只经正常本机路由读取，未输出/迁移/入库。

## 当前缺口与下一步

真实仓库自主完成仍未验收。剩余证据明确指向规划/恢复契约：前置只读诊断没有声明验收命令时，早期探索失败和超时被旧式完成判据保留；只读 diagnostic 失败的重规划又变成空写范围实现。S107 的只读恢复修复仅覆盖 verification，不能误说所有只读种类已修。单纯扩大轮次不证明这些问题解决。下一刀先复用现有诊断/验证/修复语义做确定性复现和通用契约修复，不按具体 pytest 路径过滤失败、不对本题写特殊分支，再考虑同目标对照。

ACTIVE_SLICE=S108，工程回执收口后保留该索引交接；不能因本刀代码 CI 绿关闭“真实仓库自主目标”或小时级可靠性缺口。S107 的七分钟成功与 S106 的失败照旧保留。公开参考与边界取舍见 S108 brief；主流模型如何匹配工具结果的机制，只作为结果归属/错误反馈的参考，不作能力持平结论。

诊断纠错：曾在中途未完整核对 task_plan/执行证据时误称第二轮要求“尚未生成的回归文件”。原记录不支持该说法，已公开更正；本报告以实际 validation_commands=[]、读范围拒绝、测试 timeout 和后续 brief gate 为准。不得把早期猜测当路线依据。
