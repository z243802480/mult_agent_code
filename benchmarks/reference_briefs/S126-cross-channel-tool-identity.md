# S126 — 跨通道工具身份唯一性

2026-11-12，用户「继续」。已读 AGENTS、总计划 §6/§16.2 第38项及 S125 报告。原 S125 拒收记录、重复 ID 与完整快照不重编号、不补伪调用。

## 参考 → 落点 → 不照搬

[MCP 2025-11-25 规范](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/index.mdx)要求请求身份不复用，结果和错误关联原请求；这里只参考关联原则，不改变项目 MCP wire protocol 或追逐新版协议。[OpenCode 的会话身份类型](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/schema.ts)将身份视为独立字段而非事件行号。落点为 RuntimeContext、ToolExecutionGateway、ToolRegistry 和适配器记录；不复制实现，不建新编排/全局共享计数服务。

## 已证事实与最小方案

S125 47本地调用+1技能 invocation=48观察=预算48，费用和技能有出处；真正冲突为技能与下一本地工具共用 toolcall-0023、观察 ID 亦重复。两个生产编号点都数本地账本行。成功 skill/MCP 分支通过独立证据回传，未推进本地行数；不能通过塞一条本地假调用修复它。

改为调用开始前生成 toolcall-UUID，身份为不透明字符串，不再表示行号/时间顺序。经内部 RuntimeContext 传给本地记录，适配器自身记录可选同一 tool_call_id，观察与进度沿用该身份。普通直调登记也独立分配；嵌套工具清除外层绑定、分配自己的 ID。冷/暖/多进程无需重建计数器，旧 ID 与新 ID 均可读取。保留各适配器 gate、预算、invocation 账本；不双记费用，不改历史。

测试成功技能→本地、MCP→本地、适配器返回失败/抛错、预算拒绝、本地拒绝和重建 context/暖续作；真实 registry 与适配器记录必须可按同一身份对齐。并发只读登记用例检验身份不依赖账本长度，不开放新的产品并行写。schema 根/包内同步；原要求连续编号的少数断言改为关联/唯一性断言，不降低原证据测试。

## 验收与真实采样

先用确定性序列在旧执行器证冲突，再验证修复；Windows/WSL 相关、完整 Python、Ruff/类型/五基准。新真实目标从已接受 S124 源码副本开始（不带 .asteria，不用 S125 失败产物）：仅更新 usage，增加一个明确要求 doctest 形式的 remove 计数示例，验证后加载可用 retrospect 技能。此为公开目标中的工具使用要求，不伪装成自然自发技能选择，也不声称改善了任意文档形式的验证。

目标/检查器经实际 RunCommandTool 同环境预检，基线缺新示例为红、正控制为绿，冻结输入/执行器后再调用。默认 profile/provider、原预算权限、900秒外部上限，一个目标；不提示实现或代修产物。检查文档实际执行、原项目测试、严格单文件范围/来源/typed 边界、所有通道身份与计量，全部过才正式 Review→Accept。未调用技能就不称真实跨通道已证明；MCP只确定性验证，不声称远端实跑。失败保留，不重跑刷绿。

收尾更新计划/ACTIVE/报告/本机记忆；provider key 不进Git，远端浏览器镜像DNS故障/UI未运行仍如实记账。

失败分支回归追加核实：现有 McpAdapter 对正常 RPC 返回的 isError=true 仍写 success。[MCP工具错误契约](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)明确它是工具执行失败。此处窄修状态映射、保留完整响应给模型；不将其变成自动 transport 重试。与失败分支身份/计量一起验证，不扩展协议版本或错误词启发式。

同一身份的终结观察也只能有一条：本地失败结果已记录后，为停止批次抛出的控制流异常不应再写第二条观察。适配器观察引用其实际 invocation 账本；未产生的记录不伪造引用。
