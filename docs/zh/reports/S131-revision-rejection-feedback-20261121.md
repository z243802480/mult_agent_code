# S131 方法修订拒绝的来源事实与精确引用

日期：2026-11-21。基线8a8b4cf，生产源码冻结b70f689f5db91c90c98fd7756c369433053231e7。工程及定向真模型反馈控制通过；自然坏件仍漏检、新正向拒收，S131保持开放。

## 确认的通用缺口

只读复核上一轮66条观察：59/65因替代通过后又执行未登记shell而陈旧拒绝；64失败ID拼接不存在。三条拒绝的data都只有本次tool_call_id，真实错误文字及原stdout/stderr存在，不是丢反馈。没有返回造成失效的观察、已选失败/通过身份或可核对的当前执行收据。原始需求、方法来源、任意shell可能写与stat只观察不授只读权的口径保持。

进一步在相同旧任务/目标/指导/前59条观察上纯函数只读重放：旧冻结eb71de8与新冻结b70f689都按相同错误拒绝；新版准确返回42原失败、56替代通过、58失效shell的原始ID/hash与dispatch。0新模型/工具调用，任务对象和旧账本均不变；这证明反馈来源，不冒充模型真实消费或新任务成功。

## 修复机制与边界

抽出原commands_needing_execution的共同索引扫描，完成闸与修订仍使用同一规则，不另造宽松新鲜性判据。只有已有陈旧拒绝分支和未解析执行引用分支产生带事实的PermissionError子类；修订工具将它转为普通denied结果，保留原错误和状态，经真实网关、账本与模型payload返回。其他权限/来源/预算拒绝、全局工具错误处理、shell及提示/模型JSON不变。

陈旧拒绝带回原失败、替代通过、实际最后一个可能写入的观察的ID/工具/退出码/dispatch与240字符命令摘要及hash；不声称“发生真实写入”，不自动重新验证或选择/采用替代。未解析引用仅列同run/task的唯一一致近期8条验证观察，明确total/truncated，重复ID/跨run-task/内外事实不一致不混入；不猜近似ID，不以摘要替代原命令执行。所有覆盖判断仍unassessed。

参考[MCP工具执行错误及结构化结果规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)：将执行错误作为模型可消费结果，结构化数据是服务端产出的事实；只借返回机制，不要求模型输出额外认知结构，不扩MCP/新编排或复制实现。

## 工程验证

8个新单元实例原版7红/1过。2个真实Execute流程实例覆盖：先陈旧拒绝→模型回灌→重新执行替代→无效ID拒绝→从真实收据取精确ID→修订→原必需检查；合法产物Review/Accept通过，坏产物在完成闸被拦，目标/来源/必需检查/范围保持。属于确定性模型夹具，不冒充真模型自主发现。

Windows相关106过62.79秒，WSL相关106过64.57秒；含原权限/来源/副作用/未知dispatch/前置拒绝/跨run-task/重复/歧义/新鲜性控制。Ruff通过，类型棘轮无新增（60 known/18不再出现，未改baseline），五离线基准通过；Python3.11语法解析通过。最终Windows全量2279过/8跳过/42排除/2警告，572.21秒。

## 自然真实复验

新独立副本、冻结b70f689，同原目标/指导/基线/v1/v2/13控制，32轮900秒，坏件标准Review和自然正向各一次；无oracle/在途解答或清理批准，独立合格且原生完成才正式Review/新鲜Accept。不续跑旧场、不无改复采。

| 场景 | 耗时与用量 | 实际结论 |
| --- | --- | --- |
| 真实坏件标准Review | 65.52秒，3新模型64320入/875出，2真检查 | 项目271过1跳过；局部自选方法exit0、未输出attempted。Review仍pass1漏标题29/线28；独立拒收、Accept NOT RUN |
| 新自然正向 | 850.57秒，17条模型记录（其中1失败usage未知），22观察 | 原生blocked/EXECUTE，非900秒外部终止；provider写入超时，正式Review/Accept NOT RUN。项目271过1跳过、仅改允许文件/added0，但独立v2拒收、标题29/线28，不能因项目测试绿签收 |

坏件快照31判据和627字符当前差异均存在，无section截断；两个自选真检查后仍总结样式与所有要求已满足。局部方法继续绑定当前28字符锚点，没有验证它是否符合原始适用条件。requirement_coverage仍null/unassessed，不把登记来源/exit0/模型pass当运行时全面覆盖认证，也不按工具数判错。

正向实际只执行2条shell检查，末条自拟here-document方法报StopIteration，stdout/stderr留在payload；另有empty_patch、diff_workspace缺少必需参数等工具失败。最后task.notes与失败调用指向provider write timeout，一条task_execution记录input/output为null。不能把850秒全部归因于模型不收敛，也不把传输失败归为本刀反馈机制失败。0次revise_verification/verification_ref执行/权限请求，未触发新增拒绝事实；不能据本场证明反馈的实际消费或治愈。

## 独立真模型反馈控制

自然场未触发修订后，先在brief补登记一个新只读小任务，不重跑原题：controller创建值为42的工件、原始必需命令和规划故障方法，经普通网关执行失败、已通过替代及后继shell，再产生陈旧和无效ID两类真实拒绝。只有这5条原生观察作为prior_progress交给同冻结源码的普通模型循环/既有系统提示，最多8轮180秒，无在途答案；模型自行选择后续动作，外部核对新鲜性、原必需检查、精确引用与工件不变。

首个诊断fixture在设置不可变网关agent_id时退出，0模型，5条controller种子/6工具预算单位；属于诊断接线错误，NOT RUN，原场/日志保留。只修临时诊断接线为新网关副本，另开control-b新场单次运行，生产源码与原自然场均不改，不把0模型预检混成付费模型采样。

control-b共93.36秒（循环91.99秒），8次MiniMax-M2.7、70472入/1817出；5条种子+9条模型自主工具观察，循环completed。模型重新执行原失败和替代方法，使用新的真实失败/通过ID及原verification_ref成功修订1次，然后完成保留的原必需检查；外部确认替代新鲜、原要求命令保留、工件字节未改。引用绑定逐条与账本关联，均未猜测/自动改写。没有审批或清理请求。

这是预置故障/候选方法/拒绝的定向诊断，证明该接口能被真模型使用；不是自主发现、自然全链或成对因果/稳定性证明。Goal/正式Review/Accept均NOT RUN。两个诊断工作run只用于引用绑定，worker结束后通过原生cancel关闭，保留全部种子/账本；不把诊断循环completed写成产品验收。

## 计量、保留与交接

三场付费（坏件/自然正向/定向控制）加一个0模型预检，共28条真实模型记录：27有usage，1传输失败usage未知；已知token合600396入/17280出，不宣称精确总费用或把未知当0，不退该失败尝试的预算。原自然两场20记录529924入/15463出，控制8记录另列。没有新增未记录在途预留；上轮1笔未知在途与旧4001均保持。

新43调用/观察全部关联且全局ID唯一，43收费/33工具预算单位。其中33模型自主观察（坏件2、自然22、控制9），10controller种子（两个诊断各5）；旧坏件24模型/41工具前缀另计，不混新。两次纯函数旧现场重放0模型0工具，不属于这43观察。无MCP/skill执行，原请求与requested_command保持同字节，没有自动shell改写。

final/closing/detail/stop审计通过：源码冻结不变、原件/baseline/旧账本前缀与40处旧现场hash保持，所有本次新进程组已空。自然新正向保留blocked状态；旧DB/待批/旧无进程runningREVIEWED现场和全部预留不代批/删/续跑/cancel。所有新helper已结束，不重启或无改重采。

私有证据~/.cache/asteria-evaluations/s131-revision-feedback-20261121：registration、prior-feedback/prior-hashes、prior-replay-baseline/fixed、negative/positive-result、control/control-b-result、final/closing/detail/stop-audit。工作副本s131-revision-feedback-negative/tables/control/control-b与冻结运行时同前缀。日志位于Windows临时目录asteria-s131-revision-feedback-*，私有运行/路由/本机记忆不入Git。

已更新总计划§16.2/1.2.270–271、brief、当前状态/vibe/AGENTS指针和本机记忆。下一核实Review是否以派生方法/当前实现锚点代替原始适用条件，及其验证结论对原要求的实际覆盖与有效替代；provider就绪后在实质修复或新假设下再登记复验，不无改重采。继续通用harness机制，不放宽授权、不自动改shell、不堆提示/强制工具数/领域专补。Verify禁用时NOT RUN，不启workflow或读key。S131尚未收官。
