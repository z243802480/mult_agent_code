# S131：验证方法来源、失败观察与修订入口闭环

2026-11-16。本刀工程相关检查通过，完整套件与真实模型待结束；不能预签真实缺陷或整链已通过。前置：[Review可执行证据报告](S131-review-executable-evidence-20261116.md)，执行真源为总计划§16.2行43。

## 核实与修复

原方法1100字符，两次修订请求1104字符，仅多了引号转义。来源守卫正确拒绝；不能把“看起来相同”变成有权替换。原循环反馈没有稳定调用引用，修订成功的结构结果也没有进入模型可见payload，旧入口要求模型再次重写整段shell文本。

新增通用verification_ref，绑定持久run目录命名空间、run/task、登记命令与方法来源版本；run_tests可引用执行登记原字节，raw command仍兼容。不解析、规范化或改写shell。批准预检、网关、工具均针对同一当前持久任务解析，并用完整实际命令检查既有权限；引用是数据选择器，不是授权或抗篡改签名。非running运行、非in_progress任务、跨工作区/run/task、过期版本、重复任务、撤回工具或混用command均拒绝，未知引用不会变成默认pytest。

模型种子增加当前方法机器索引，通用观察反馈回传tool_call_id/verification_ref/实际退出码；微压缩也保留引用。revise_verification支持original_verification_ref及失败/成功执行receipt ID，从当前run/task的唯一schema校验观察读取原方法与替代命令。继续复用原来源指纹、实际先失败后零退出、无观察到副作用、写后新鲜度与最新结果检查；拒绝伪造、跨run/task、重复、旧结果或受保护方法，不改变原要求/必跑项目检查。旧精确字符串接口保持严格，不将旧转义近似串自动授予来源。

修订后回传新索引并刷新现行任务；历史原失败保留，旧ref失效。持久reference_binding使用现有SchemaValidator已支持的object/required子集，不引入依赖或声称未实现的JSON Schema关键字已执法。Native参数schema表示两种互斥输入，实际工具也检查互斥。只改数据/工具协议，不改执行语义rubric、共享验证指导或EvalReport输出契约；不加模型/文档格式分支。

参考 [Anthropic工具定义](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) 的稳定标识和机器参数、[工具循环](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) 的结果对应；只参考通用机制，不声称这些产品具有本项目具体修订授权规则，也不复制代码。

## 目前验证与预登记

最终新单元/生产生命周期Windows27过，包含真实工具失败→成功→引用修订→保留必跑检查→Review→Accept，以及错误产物仍拦。旧严格接口/早期闭环批59过；WSL相关117过；Ruff、类型无新增、文档23及5个离线基准通过。完整Windows正在跑，结果待登记。测试准备曾误把原始ToolResult.status=None当失败状态、复用的planner夹具输出路径与目标不一致、引用Schema测试误假设安装了jsonschema；已校正夹具/用现有校验子集，未安装依赖或放宽断言目的。

旧4001失败现场零模型、零工具执行回放：两条1100/1104引用差异保持，new ref精确选择原1100字符串；已取消历史运行仍禁止执行，全部原始文件/账本字节保持。私有结果~/.cache/asteria-evaluations/s131-method-reference-audit-20261116/result.json。该回放不把旧失败补成可授权成功，也不修改旧现场。

冻结源码后只各跑一次：旧真实坏件副本标准Review（无缺陷/oracle提示、不Accept），以及同冻结名表题/通用AGENTS/13控/v1诊断/v2验收/32轮/外部900秒完整Goal。独立示例/原项目测试/旧行/范围都合格才正式Review并复用新鲜报告Accept。原件、旧失败/历史正向、在途与中断预留保持，不无改重采样、不换容易题。无外部解答、临时清理授权、额外语义提醒或格式补丁。真实引用/修订若没触发就写未触发，工程回归不能冒充真实独立交付。
