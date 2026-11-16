# S131：验证方法来源、失败观察与修订入口闭环

2026-11-16。**方法引用工程与本次正向完整流程已验；旧真实坏件仍被Review漏检，新引用入口在真模型中未触发。** 实现源码1d029833f3cb2fc0c630ccf2691c9f96ea7d2248。前置：[Review可执行证据报告](S131-review-executable-evidence-20261116.md)，执行真源为总计划§16.2行43。

## 已核实并修复

上轮登记方法1100字符，两次original_command请求1104字符，仅多了引号转义；来源守卫正确拒绝，不能把“看起来相同”视为有权替换。原循环反馈缺稳定调用引用，修订成功的结构结果也没有进入模型可见payload，旧入口需要模型再次重写长shell字符串。

新增verification_ref，绑定持久run目录命名空间、run/task、登记命令和方法来源版本；run_tests可引用执行登记原字节，raw command仍兼容。不解析、规范化或改写shell。批准预检、网关、工具都解析同一当前持久任务，并针对完整实际命令/参数走既有权限。引用是数据选择器，不是授权或抗篡改签名。非running运行、非in_progress任务、跨工作区/run/task、旧版本、重复任务、撤回工具或混用参数均拒绝；未知ref不能落成默认pytest。

执行种子增加当前方法机器索引；通用反馈回传已有tool_call_id/verification_ref/实际退出码，微压缩仍保留引用。revise_verification可用original_verification_ref和失败/成功receipt ID，从当前run/task唯一schema校验观察取得原方法和替代命令。继续复用原来源指纹、实际先失败后零退出、无观察到副作用、写后新鲜度及最新结果检查；拒绝伪造、跨run/task、重复、旧证据和受保护方法。旧精确字符串接口保持严格，不自动为近似字符串赋予来源；原失败、要求、必跑项目检查及权限都保留。

修订后回传新索引并刷新现行任务，旧ref失效。持久reference_binding用现有SchemaValidator已支持的object/required子集；Native参数schema表达两种互斥输入，工具本身也验证互斥，不引入依赖或假装未实现的schema关键字已执法。Execute仅四处小接线，不重构执行循环。执行系统提示、共享验证指导、Review语义rubric和EvalReport输出schema与e69基线保持；仅改机器数据/工具协议，无模型/文档格式分支。

参考 [Anthropic工具定义](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) 的稳定标识/机器参数和[工具循环](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) 的结果对应；只参考通用机制，不声称主流具有本项目具体修订授权，也不复制实现。

## 工程与旧现场验证

最终Windows完整 **2067 passed / 7 skipped / 42 deselected，613.15秒**；WSL相关 **117 passed，45.20秒**；最终新增单元/生产生命周期27过，旧接口/早批闭环59过。Ruff、类型无新增（60 known/18不再出现）、文档23、五个离线基准通过。27例包括真实工具失败→替代成功→引用修订→保留必跑检查→Review→Accept，以及错误产物仍被拦、来源/权限/时序/副作用/新鲜度/取消与命名空间边界。

旧4001现场零模型、零工具执行回放：两条1100/1104差异保持，新ref精确选原1100字符串；已取消历史运行仍禁止执行，原项目和运行文件逐字节保持。私有回放在~/.cache/asteria-evaluations/s131-method-reference-audit-20261116。没有补授权、重置预留或改旧现场。

测试/审计准备的红也区分保留：误把原始ToolResult.status=None当失败状态、旧planner夹具输出路径与目标不一致、假设已安装jsonschema、审计脚本误以为AcceptResult顶层有workflow_state，均只修夹具/脚本或使用既有校验子集；没有安装依赖、修改验收器或放宽断言目的。最终源码一次全套通过，未把前述准备失败记成产品失败或假绿。

## 本轮真实结果

同一冻结目标/通用AGENTS/基线/v1诊断/v2验收/13控/32轮与外部900秒，保持无oracle提示、无运行中解答/修复/清理授权；每场景仅一次，不换容易题，不无改重采样。

| 场景 | 结果 |
| --- | --- |
| 旧真实坏件副本标准Review | 12.35秒，新增1 MiniMax、102618入1042出，仍pass.98 **漏检**；0工具/未建副本，完整627字符diff/29条件和工具能力可见。原件/项目/账本前缀/快照计费保持，无Accept。继承24旧模型不重复计为新调用。 |
| 同目标完整Goal及独立检查 | 164.90秒（指标包括后续独立检查），原生completed，22次真实模型；独立v2的9示例、项目271过/1跳过、旧内容和范围合格。仅docs/usage.rst改变，无额外用户文件。 |
| 真实方法修订 | 1次成功，**走旧精确字符串兼容入口**。实际原检查538字符，在/bin/sh以退出码2失败；模型自行提出并执行432字符替代检查，退出0，无观察到工作区变化，再显式修订。失败/成功ID、原方法精确字符串、时间顺序、Goal/指导/项目命令来源摘要均对账。 |
| 正式Review→显式Accept | 外部独立验收后标准Review11.77秒，1真实模型，pass.98，630字符diff/41条件绑定新鲜快照；accept --skip-review复用该报告，实际accepted=true、status=completed、review_status=pass、最终phase=ACCEPTED。无force。 |

Goal记录原生phase已为ACCEPTED，但其22次模型中没有run_review；这里不把自动promotion收尾标记当作语义Review已跑。正式Review是独立验收后的第23次调用，显式Accept结果来自真实命令输出。

**新引用入口的真实验证缺口**：本次run_tests的verification_ref调用数为0，修订history没有reference_binding。模型成功使用的是兼容入口。不能把真实旧入口修订或27例受控测试冒充新入口已经被真实模型采用，也不能把本次正确产物因果归于新引用。共享指导仍保留有效的旧API用法，未在途中改提示以制造新入口触发；未采用的原因尚未独立证明。

正向合计23 MiniMax-M2.7、761756入12209出，32本地工具/32唯一关联观察/32收费/19加权单位，无Skill/MCP。GoalSpec生产来源verified，Review请求绑定实际产物evidence_id/ref；模型与工具前缀、基线/runtime、f5原坏件、e69历史正向和4001失败（含未落账预留）均保持。两个本轮场景新增 **24模型、864374入13251出**，无未知用量差额。方法coverage说明是模型主张，运行时没有认证其语义；独立v2只证明本目标所覆盖条件。

## 当前边界与下一步

已交付：精确方法选择、执行receipt、引用修订入口、来源/权限/新鲜度守卫及受控闭环；真实兼容修订与同题正向整链通过。仍开：旧坏件Review未选独立检查而漏检；新引用入口真模型未触发。单次成功不证明稳定降本、跨provider或小时级可靠性，也不覆盖历史失败。

下一步优先核实Review所消费的验证证据是否区分编码阶段检查、独立评审检查及实际需求覆盖；同时核实新/兼容入口的可发现性与机器API口径，登记独立的通用机制控制再验新入口，不用强制认知提示或重采同题来刷触发。保持精确来源与授权守卫、不自动改shell、不加领域/格式/provider判断，不新增编排/强沙箱/无摩擦功能。副本仍非OS沙箱，stat-only无变化不证明全系统无副作用。

私有原始证据：~/.cache/asteria-evaluations/s131-method-references-20261116（registration、negative-result、positive-result、final-audit与原始命令日志），具体工作区/runtime见registration；只存脱敏结论到Git。Windows最终日志为Temp下asteria-s131-method-refs-full.log/-wsl.log/-benchmarks.log。Verify仍禁用，当前远端验证NOT RUN；推送后核对本次SHA，不启用工作流或借旧绿。
