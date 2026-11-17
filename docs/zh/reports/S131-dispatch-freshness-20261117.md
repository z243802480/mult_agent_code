# S131 前置拒绝、验证新鲜性与方法修订

日期：2026-11-17。基线0009712；生产修复冻结acd2c891a7f5435006fef2b9e5c704741bd44796。本轮先查真实暂停现场，再修通用事实与消费机制，不放宽授权、不改shell、提示词、模型回复协议或领域判据。工程机制通过；真实坏件仍漏检，新正向在另一shell审批点暂停，S131保持开放。

## 核实与修复

上轮正向在apply_patch越界删除db.json后，revise_verification报“Replacement evidence is stale after a possible write”。源码控制流显示边界检查在registry.call之前；原观察仅有PermissionError，没有分派事实。不能只靠status/零计费证明未执行，也不能把新事实倒填进旧账本。只读重放旧观察时，新旧新鲜性函数均保持陈旧：旧记录仍保守；原paused、decision-0001 pending和0字节db保持。

确认两条责任链问题：新鲜性按工具名把每个写工具请求都算作可能写入；循环从批异常另构观察，会丢失网关原观察的调用身份和控制流事实。最小修复为ToolObservation顶层可选dispatch_state（unknown/not_dispatched/dispatched），网关根据自身控制流赋值，不能由模型参数或工具data覆盖。准备批准context与实参后、进入工具注册表前才标分派；若已进入before_tool_call hook而注册表尚未进入，状态unknown，不声称无副作用。已进入注册表的预算/策略拒绝、工具失败/异常均按dispatched保守处理，不据此声称工具体或shell一定执行过。

只有明确not_dispatched且失败、无矛盾变化信息的观察不再制造新的陈旧性。请求拒绝与原失败保留；被拒绝的必跑检查仍失败，不能用此前成功覆盖。前置路径仅为计划，不再被装入该失败观察的实际file_changes；错误事件/参数仍保留请求事实。验证命令的前置异常保存原命令身份，未执行不制造returncode或成功回执。旧/未知/已分派操作、实际修改和先写后PermissionError继续使证据陈旧。新鲜性只表明后续没有已知可能写入，不认证方法需求覆盖。

批异常传递同一持久观察，模型反馈通过现有Execution receipt回传dispatch_state和tool_call_id；旧JSON仍兼容，根目录/安装包schema同步增加可选枚举校验。没有新增必填模型JSON、提示语义步骤或强制工具数。方法来源、真实失败→后续零退出且无观察变化、必跑命令、当前目标/指导和清理审批规则不变，未经授权的清理继续拒绝。

参考[Codex ToolRouter](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/src/tools/router.rs)分开构造/分派边界和保留调用身份；仅参考机制，不复制实现，也不声称参考项目使用本项目同样的新鲜性规则。

## 验证与证据边界

原版新增回归10红/1过，修复后真实前置拒绝可修订；另保留更强反向控制。对同一组新工具观察零模型比较：旧函数将替代判陈旧，新函数保持新鲜，实际revise_verification成功，但尚未执行的独立必跑检查仍缺失；禁写目标未创建。此为真实工具机制控制，非自然目标的模型自主决策证据。

确定性整链覆盖Plan→真实工具失败→局部替代成功→越界写前拒→引用修订→独立必跑→Review→新鲜Accept；包含交付坏值阻断及生成状态越界仍不授权的反向组合。控制模型的既定动作不冒充真模型能力。WSL相关108通过57.75秒，Windows整链21通过28.75秒；初步相关Windows103通过37.65秒属中间版本。Ruff/类型无新增（60 known/18不再出现）和五离线基准通过。完整Windows2179通过/7跳过/42排除579.69秒，较基线新增17项（13条分派回归、引用整链增加4组合）。没有删除或放宽原测试，未更新类型债基线。

## 冻结源码的真实复验

新目录s131-dispatch-freshness-20261117，原目标/指导/基线、v1诊断/v2与13控制保持。每场一次、无缺陷/oracle/在途解答/清理授权；8轮120秒Review、正向32轮/外部900秒。原生完成且独立合格才正式Review/Accept，暂停或独立不合格按NOT RUN记录，不无改重采。

坏件标准Review31.52秒、7新模型、5次历史查阅/0新执行，pass/1仍漏检标题29/线28；独立拒收，未Accept。没有触发本轮前置拒绝路径，不把新机制签成Review语义治愈。

正向288.84秒（含外部验收）、21新模型（goal1/plan1/执行18/recap1），原生paused/DECISION。独立9例、项目271通过/1跳过、809旧行保持与仅docs/usage.rst编辑/新增文件0均通过；标题29/下划线29。不是本次清理路径再次失败：本场没有清理请求、边界写前拒、引用执行或方法修订，31条新观察均dispatched。因此新鲜性修复的真实自主采用在这次自然题未触发，只签受控机制闭环。

失败方法最初未找到标题，后续自选方法多次退出1并报告9例失败；另三条退出0的检查明确输出selected=0/attempted=0或空section，不能作为实际覆盖成功。原失败/原必跑仍保留，方法修订成功0，不把新方法文字、退出0或独立外部9例倒算成模型验证成功。

模型随后请求的另一条完整命令含引号内Python比较candidate.start() > match.end()，审批预检被ShellGuard的原始文本重定向正则判为输出重定向，decision-0001 pending（explicit_request=false）。该请求未分派，故未制造工具调用/收费/执行观察，不能拿最后一条工具当成它的执行结果。没有运行request_execution_permission工具、代批、取消或续跑；正式Review/Accept均NOT RUN。

只读词法审计：原命令按POSIX拆为3个argv，比较符位于-c的单引号参数内，Python语法可解析；通用最小例python -c 'print(2 > (1))'同样被拒，真实echo重定向到../outside.txt仍被拒。该诊断只调用解析/守卫，未执行任何命令，也不证明原大方法运行结果。确定是引号内容与真实shell重定向混判，但本刀**未修改ShellGuard**：通用修复需同时核实宿主shell语法、引号/转义、嵌套shell与真正重定向的拒绝不变式，不能为这条命令跳过守卫、自动改写shell或扩大许可。见redirect-readonly-audit.json、positive-pause-detail.json。

两场28新增MiniMax/MiniMax-M2.7，910658入19681出、未知token0；36新调用/观察、36收费35单位（负控5、正向31调用30单位）。旧24模型/41工具/1旧修订单列，未重计为新增。唯一身份/模型与工具计量/有界Review来源/原件/运行时快照/此前列明现场哈希核对通过。10条可比较实际命令与输入逐字节相同，未自动改shell；所有原正负控、旧DB/审批/4001预留与新pending保持。

## 交接

保持全部历史现场、账本、DB/审批和4001未知预留；不继续旧paused运行，不自动清理或代批。旧整链成功仍属旧源。私有证据在~/.cache/asteria-evaluations/s131-dispatch-freshness-20261117，mechanism-audit.json记录旧60文件哈希及新机制对照；本机日志/现场/凭据不入Git。S131自然坏件漏检及本轮整链仍开，不以本次机制修复代签。下一优先核实并修复跨shell语法下的重定向识别/审批反馈闭环，保留危险目标与嵌套shell守卫；同时核实“退出0但实际执行0项”的方法观察如何被模型用于修订与评审，不能用领域格式规则认证语义。待新通用机制有依据后再新冻结一次真实流程，不无改重采。

完整证据：registration/final-audit/closing-audit/mechanism-audit/redirect-readonly-audit/positive-pause-detail.json及原日志。远端状态只以推送后当前SHA核对；Verify禁用时NOT RUN，不启用workflow或读取密钥。
