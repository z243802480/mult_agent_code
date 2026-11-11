# S126：跨通道工具身份与失败观察

2026-11-12；[brief](../../../benchmarks/reference_briefs/S126-cross-channel-tool-identity.md)。执行器 `2efea9da92c1e43dc7b68cf94a25bded66d6089a`。

**身份修复工程通过，新的真实目标整体拒收。** 完成记录中 106 条本地调用 + 2 条技能记录与 108 条观察逐一对应，身份及观察 ID 均唯一。但任务在旧文档验证中持续绕行，触及 900 秒外部上限，且生成三个未授权数据库文件；正式 Review/Accept **NOT RUN**。不把一次修复已成立外推成完整任务自治已成立。

## 工程结论

工具身份不再由本地账本行数决定。Gateway 在调用前分配不透明 UUID，观察、进度、本地记录和适配器记录沿用同一身份；Registry 直调也分配身份，嵌套工具清除外层绑定后独立分配。重建 context、暖续作与不同进程不需要恢复共享计数器。顺序仍以账本和时间为准，旧顺序字符串继续可读，不重写 S125 历史失败、不塞伪造本地调用。

Skill/MCP 持久化 schema 只增加可选关联字段，根目录与包内一致。权限、预算和各自 invocation 账本责任保留，不双记费用。适配器观察引用各自账本，文件尚不存在时不伪造路径；`evidence_refs` 是账本级引用，不代替逐条按 ID 对账。本地失败因停止批次抛出的控制流异常也不再重复写同一身份的观察，原工具输出保留。

失败回归还核实了 MCP 的 `isError=true` 被误标成功。现按 [MCP 工具错误契约](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)标为工具失败，完整响应仍交回模型；不追加 transport 重试或按错误词替模型决策。身份机制参考 [MCP 请求关联原则](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/index.mdx)与 [OpenCode 会话身份类型](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/schema.ts)，没有复制实现或修改 wire protocol。

## 确定性与环境验证

同一组跨通道用例在冻结 S125 执行器上 **6 failed**：成功/失败/拒绝的技能、MCP 接续本地工具均暴露身份冲突或 MCP 错误被标成功。确定性验证无模型调用，原执行器目录未修改。修复后相关 Windows **67** 项通过，最终身份/检查器/文档契约 **45** 项通过；WSL 最终相关 **50 passed**。

最终代码的 Windows 完整 **1836 passed / 4 skipped / 42 deselected**，592.81 秒。较早一轮 1832 通过发生在最后失败路径及检查器测试变更前，不把它当最终版本凭证。Ruff `src tests scripts` 通过，类型 ratchet 无新增（60 known，18 项已不再报告但未重写基线），五个离线基准通过。`ruff check .` 仍报既有未跟踪 `validation_multi_file_scope` 的两项错误；该目录与另外五批既有输入均未修改、未暂存。

产品提交的 [Verify 43057943060](https://github.com/z243802480/mult_agent_code/actions/runs/43057943060)：Python 3.11/3.13 完整 job 通过；Studio 安装浏览器依赖仍报 `Temporary failure resolving azure.archive.ubuntu.com`，UI 未运行，整体 CI 为失败。未以跳过 UI 或修改 workflow 刷绿。

## 单次真实目标

从已正式接受的 S124 源码复制，不带运行状态，不采用 S125 失败产物。目标明确只改 usage 文档，在 Batch Operations 中增加自包含的 remove 计数 doctest，保留其它内容，运行原项目测试；验证后加载 retrospect 技能。这是公开工具使用要求，不冒充模型自发选择该技能。冻结检查器不进模型工作区；基线缺新例子为红、正确正控制为绿，原项目 **271 passed / 1 skipped**。

实际默认 `session_agent`，原权限/预算，900 秒外部上限；一个新目标，没有中途提示、人工编辑或重跑刷绿。到期发出取消请求后控制器终止进程，包含取消命令耗时共 **906.52 秒**，返回码 `-15`。原 run 状态文件仍是 `running`，任务仍 `in_progress`，不能称 Runtime 已正常阻塞、取消或完成；目标进程已确认退出，旧状态原样保留。

完成模型记录 **42 条**，均为真实 MiniMax-M2.7；输入 **1,473,876** / 输出 **63,325** tokens。它们是已完成记录之和，不是服务端账单，不能覆盖终止时可能在途的请求。配置警告提示 cheap 档是假 provider，但本次记录没有 fake 调用，不据此宣称独立 provider 验收。

独立检查 usage 的 Batch Operations **12 次尝试/0 失败**、API **4/0**；新增示例隔离到空上下文 **7/0**。隔离检查重复验证同一组新语句，不是额外七个独立示例。原项目 **271 passed / 1 skipped**。真实 diff 只插入目标小节，原文保留，所有原有其它文件哈希不变。

然而源目录新增 **`db.json`、`db1.json`、`db2.json`**，违反不得新增用户文件的目标。额外用 evaluator 自有的两个全新副本独立复核：旧原文与加入新例子的文档，直接执行整份 usage doctest 都失败，都生成同样三个文件。这证实了验证副作用的来源；没有在模型工作区删文件、补改示例或重跑目标。

人工审阅全部 106 条本地工具输入及四次补丁（第一次格式失败，后三次成功），未发现网络、秘密、evaluator/执行器访问或依赖安装。模型自行选 debug 技能，按公开目标另加载 retrospect；两者均成功。54 条 run_tests 中含重复完整 pytest、整份旧文档、管道筛日志和临时过滤/替换 doctest runner 的诊断。模型后来已有直接隔离新例子的成功证据，却继续研究旧失败，不能把管道末端的 0 或输出过滤脚本当整份文档已通过。

最终原输入与冻结执行器哈希保持。106 本地 + 2 技能 = 108 观察，调用/观察 ID 唯一、逐条关联正确、证据路径存在，未复现 S125 冲突。MCP 本次未调用。这只验证了完成部分的跨通道关联。

**累计费用未对账成功。** 强制终止未经过正常 run 收尾，原 `cost_report` 停在规划后的 **2 模型 / 0 工具**。不覆盖它、不把推算的 108 当持久预算实测、不混同为成功技能分支漏计，也不据此直接断言恢复代码会重置预算。强终止后的状态/计量重建需另做无模型回放审计，本次整体 `source_qualified=false`、`independent_accepted=false`。

## 下一项

**S127：验证过程的范围与收敛。** 基于这次完整失败轨迹，先复现“新产物已隔离通过，仍反复执行失败的整份旧文档”和验证生成未授权文件。对照主流机制，审计既有验证观察/基线/进展与提示通道，选择通用的最小修复；保留用户必需命令、如实报告原有失败、区分诊断输出与证明，避免改造 runner 来制造通过。原生文档形式的覆盖缺口与 S125 一起保留，不能以更严 JSON 或特定文件名补丁代替语义验证。

后续 S128 单独审计异常终止后的真实状态与累计计量恢复；先用本次快照确定性复现，不把控制器 SIGTERM 等同产品正常取消，不先写结论。两项都不重启本地 OS 强沙箱、新编排 Wave 或任务并行写，不自动清理本次失败目录。

## 证据与边界

WSL 证据 `~/.cache/asteria-evaluations/s126-tool-identity-20261112`，工作区 `~/.cache/asteria-workspaces/s126-doc-remove`，冻结执行器 `~/.cache/asteria-runtimes/s126-2efea9d`。远程 MCP 只做确定性适配器回归，未做真实远端调用；不由一个样本外推小时级、独立 provider 或成对因果证明。keyed nightly 仍为 `NOT RUN`，不向 Git/GitHub 上传 provider key。
