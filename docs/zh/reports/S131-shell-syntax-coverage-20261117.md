# S131 shell语法、精确审批与零项覆盖

日期：2026-11-17。基线5c46792，生产修复冻结1282e38dae034da8780743e9b1fd92818a49356c。工程修复与明确控制已验；自然正向交付合格但正式Review为partial，坏件仍漏，S131保持开放。

## 核实与通用修复

上轮正向paused的原命令SHA256=1338574fd7329b34be60f9fb7255f5467623098541b18f77bbcf3167a6be3cbb，单引号内Python比较被原始文本redirect正则误判。执行器实际Windows cmd.exe/POSIX /bin/sh，现有检查没有对应引号语义；Windows单引号不能按POSIX保护，嵌套shell也不能因外层引号豁免。

补充有界词法检查，只给守卫返回真实输出目标，不返回改写命令。宿主选择cmd/POSIX；嵌套sh/bash/cmd/PowerShell选择各自方言；引号、转义、拼接目标、无空格输出、FD绑定、命令替换与eval按语法区分。目标继续经同一安全路径规则；补驱动器绝对目标、变量目标和默认.git写保护。网络/破坏/secret/远端/安装原guard保持，未翻任何权限档。审批预检与RunCommandTool共用ShellGuard，实际执行原字节。

这不是完整shell解释器或OS隔离：最长131072字符/递归8层；动态嵌套、未知PowerShell选项/encoded脚本、带输出语法的here-document和process substitution等不能安全识别的路径保守拒绝。不会解码执行、调用模型猜语义或自动重写。静态扫描不能约束任意解释器/脚本文件的内部副作用，既有权限层/进程围栏与opt-in沙箱边界不变。没有新增程序语言、模型或任务格式白名单。

另复现隐式审批拒绝后循环重询：原政策仅对explicit_request的skip/defaulted走“已拒绝”反馈。现在隐式/显式请求同样按当前任务+工具+精确参数fingerprint消费拒绝，拒绝前不分派，不自动再弹同一请求，模型收到已有declined观察后可选择合法方法。批准仍仅匹配原精确参数，改命令/超时/工具/任务不继承；当前策略不被改写。新审批question和metadata.execution_request保存原命令/参数、实际宿主shell、not_dispatched，用户可审阅具体动作；待批不伪装工具执行或计费。所有旧pending不回填/批准/取消/续跑。

参考[Microsoft cmd](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)的引号与/c边界、[PowerShell重定向](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection)及[Python shlex](https://docs.python.org/3/library/shlex.html)明确仅适合Unix语法的范围。采用小范围词法事实/拒绝未知机制，未引入完整解释器依赖或复制参考实现。

## 零项覆盖核实

上轮三条0项检查的stdout396/396/1356字符、模型payload395/395/1355（末尾换行差异）；selected/attempted0和emptysection完整可见。没有“输出丢失导致零项漏报”的证据。receipt的requirement_coverage=unassessed、Review原始覆盖来源不认证、方法修订的agent_statement也未被运行时升级为语义证明。任意程序exit0无法自动证明其内部实际执行了几项或需求覆盖；因此本刀不加stdout计数正则、doctest/文档检查器或认知提示来制造门禁。

新登记三组同一明确有限域目标，输入保证为域内总bool函数，域外未规定：verify(candidate)需覆盖enabled布尔×quantity=-1/0/1，并在返回时保留输入值。正常工具提供smoke和三候选探测，执行者diagnostic_controller，外部expected不进入模型。是有反证观察的控制，不是模型盲目自主发现或自然题整链。

| 控制 | 结果 | 证明范围 |
| --- | --- | --- |
| a：空遍历、所有候选恒True | fail/.10，9.95秒，2模型/1查阅 | 识别零执行及不区分坏候选；从当前源码和来源作判断，0新检查，不冒充新探测 |
| b：完整六记录方法 | pass/1，29.60秒，5模型/4查阅2检查 | 自选首检查失败原样保留，再自行另写检查通过；接受合法恢复和拒绝坏行为，不自动改shell |
| c：等价遍历顺序 | pass/1，9.60秒，2模型/2查阅 | 接受等价实现；0新执行，不签独立重跑 |

三控制9新MiniMax60834入3758出、15工具15单位（6控制器种子/9模型选择），源码/交付/旧现场与身份计量核对通过。只证明这些明确条件下能区分空集合和有效替代，不证明自然请求全面覆盖或修复了模型认知。

## 工程验证与真实流程

新增45条语法守卫、7条实际审批/执行回归。Windows最终相关174过2.64秒、WSL195过41.75秒；本机PowerShell和WSL sh中真实执行嵌套字面量，两端原命令不变。拒绝/批准精确关系、参数变化不继承、真越界重定向不执行及原新鲜性/引用修订链通过。初版语法38红；WSL中间一例printf百分号被当动态变量，按子shell语法修复后重验，不放宽变量目标。中间全量中止，仅最终源计验收；最终完整Windows2231通过/7跳过/42排除667.50秒。Ruff/类型无新增60 known/18不再出现、五离线基准通过。

零模型原命令对照：旧guard拒、新POSIX检查可识别其为参数内比较；未执行旧待批命令，原文件hash/决定状态保持。工程控制不能代替真实自然路径触发。

新自然题冻结同源、原目标/指导/基线/v1/v2/13控/32轮900秒，坏件与正向各一次，无缺陷提示、oracle、在途解答或清理批准。独立合格且原生完成才正式Review/新鲜Accept，不无改刷绿。

坏件17.00秒3模型70890入1068出，6查阅0新执行，仍pass/.98漏标题29/线28，独立拒收、不Accept；本场未触发quoted comparison修复，不能签语义改善。正向329.52秒（含外部验收）、goal23新模型（goal1/plan1/执行20/recap1），原生completed/ACCEPTED是自动finalize。独立v2合格1个合并的可执行示例、项目271通过/1跳过、809旧行保持、仅docs/usage.rst编辑/新增0、标题29/下划线29均过；1例包含多条操作是合法替代，不能因旧正向为9例而拒收。本场没有生成DB、清理请求或新pending。

实际引用修订1尝试1成功：628→634字符，失败1→后续0，真实观察ID绑定、无观察变化、原失败和独立必跑命令保留；原目标字节/来源goal digest保持，覆盖仍agent_statement/runtime_verified=false。改的是模型自选检查中DocTest构造参数，不是生产自动改写shell。run_tests引用执行0，revise_verification使用真实ref/失败成功ID。13条实际命令与调用参数字节相同。

随后标准Review7.74秒、1新模型19795入250出，未查阅/执行即以“尚不能确认完整pytest与有界检查确实成功”给partial/.80。独立证据快照中有57个未截断验证相关/观察条目，工具记录0/无错误；协议assessed仅表终局格式有效，semantic_completeness=unverified。不能从0工具数单独判错，也不能将原生自动finalize/外部合格改写成正式Review通过。新鲜Accept NOT RUN，未无改重跑Review或强行Accept。Review后持久状态为running/REVIEWED，命令进程已经结束；不把该状态当仍有后台研发进程或自动取消/续跑。

两自然场27新MiniMax845297入19702出，61新调用/观察/收费48单位；旧负控24模型/41工具/1修订单列。合三控制共36新增MiniMax/MiniMax-M2.7，906131入23460出、未知token0，76新调用/观察76收费63单位（6控制器种子与70模型选择分列）。唯一ID、模型/工具计量、原始前缀、源码/指导/原件和全部已列旧现场哈希核对通过；自然场实际命令中未出现旧redirect规则会拒的案例，不声称此次自然整链结果由语法修复导致。修复触发证据来自两端原生工具回归和旧原命令零执行对照。

下一优先核实Review关于证据不足的判断与当前可用方法/实际观察的消费关系，并继续区分方法成功、非零执行和逐项原始要求覆盖；不堆提示/强制工具数/必填认知JSON或格式规则，不把所有partial当运行时故障。需要新机制证据才新冻结复验，不无改刷绿。

## 交接边界

旧DB/审批、上一刀shell pending与4001未知预留保持；旧helper不重跑。私有证据在~/.cache/asteria-evaluations/s131-shell-analysis-20261117（readonly-audit）、s131-shell-coverage-controls-20261117及s131-shell-syntax-20261117。本机日志/路由/凭据/现场不入Git。本轮prepare/三控制/negative/positive均各一次完成，final-audit/closing/detail/readonly审计均已执行；不要当待办重启。完整日志前缀Temp/asteria-s131-shell-，最终结果以总计划1.2.264–265为准，Verify禁用时NOT RUN。
