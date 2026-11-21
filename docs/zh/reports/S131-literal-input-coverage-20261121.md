# S131 方法实际覆盖与literal here-document

日期：2026-11-21。基线df8179d；生产修复冻结eb71de8356ea287c55d01ea6c4c22cb7caa4f66c。工程回归通过；真实坏件Review仍漏检，新正向产物合格但超时未完成。S131保持开放。

## 方法实现锚点的实际核实

使用上一刀真实坏件的登记方法和Review自选局部方法原命令，在三个新隔离副本执行，不修改原交付/方法/账本，不将外部oracle或结果送给在途模型。诊断使用普通工具网关，执行者diagnostic_controller，不冒充模型自主发现或新产品运行。

| 副本 | 登记方法退出 | Review选择方法退出 | 原独立判据 |
| --- | --- | --- | --- |
| 原坏件 | 0 | 0 | 拒收 |
| 仅修真实缺陷，其他内容不变的有效替代 | 1 | 1 | 合格，9例 |
| 改错输出的坏行为副本 | 1 | 1 | 拒收 |

两方法沿用当前标题字节锚点，能拒绝部分坏行为，却不能证明原始要求中的样式条件，且拒绝有效替代。原始要求并未因此被运行时改写；这是方法/Review结论覆盖的问题。不能把“引用来自登记来源”“真实执行0”或方法修订声明当作需求覆盖认证。此次没有在生产中加入任何文档、语句或模型专用规则；现有requirement_coverage=unassessed保持。

## 确认并修复的shell边界

上一正向here-document命令的Python载荷语法有效，但词法器将标准输入正文当shell语法，正文自身引号导致Unfinished shell quote。POSIX引用分隔符使正文作为literal输入传递，不进行宿主shell正文扩展；此边界适用于输入消费者，不按Python或文档白名单选择。

在原131072字符/8层有界词法机制里增加可确认的单命令quoted delimiter、精确结束行和<<-制表缩进识别。正文不改变宿主shell引号状态；分隔符之后的输出重定向/命令继续检查。动态/未引用delimiter、多here-doc、复合header、shell/eval/source消费者、复杂/缺少结束行继续保守拒绝；非POSIX不继承literal规则。只做识别，不执行/重写/规范化原命令，不授予shell或清理权限。

完整原命令仍执行既有secret/破坏/网络/远端/安装深扫描，literal正文不是这些守卫的豁免。新增反向测试暴露分隔符后多行命令的leader扫描原本忽略换行；现在未引用换行按命令分隔处理，并对literal输入后的真实命令独立复用同一守卫，防止正文引号隐藏后继network/destructive leader。不会将未知语法自动修好，也不把静态guard当OS沙箱。

参考[dash手册的here-document与引用分隔符](https://man7.org/linux/man-pages/man1/dash.1.html)：引用delimiter后的正文作为literal输入、<<-仅剥前导tab。只参考词法机制；本刀支持有界子集，不声称实现完整POSIX解释器。原网络/破坏/secret/remote/default权限保持。

## 工程与只读验证

新增25条测试：正文引号/比较/精确分隔符/<<-、正文后的真redirect/后继命令、动态/多重/复合/shell消费者/未知/跨平台保守，以及WSL真实工具执行/审批同源原字节。首批原版11失败/11通过/1跳过。最终Windows相关194通过/1跳过3.75秒；WSL208通过9.55秒，含真实literal stdin执行。Ruff/类型无新增（60 known/18不再出现）；最终完整Windows2269通过/8跳过/42排除609.20秒；五离线基准通过。最终文档契约23通过。新增POSIX原生执行测试在Windows跳过，WSL实际执行通过。中间3.11语法兼容写法修正后旧全量已中止，只有最终冻结源码的全量作为验收。

旧pending原命令只调用修后guard可识别，未执行它；旧坏件/全部待批hash保持。方法三副本6次普通工具诊断属于新隔离工程观察，0新模型，不混入产品真模型计量。

## 真实复验

冻结eb71de8，同原自然目标/指导/基线/v1/v2/13控、32轮/900秒，坏件标准Review和正向各一次。无oracle/缺陷提示/在途解答或清理批准；原生完成且独立合格才正式Review/新鲜Accept，暂停/失败据实，不无改复采。

| 场景 | 实际执行 | 结果与边界 |
| --- | --- | --- |
| 真实坏件标准Review | 50.55秒，2新MiniMax、2次run_tests | 局部9例与项目271过/1跳过均退出0；Review pass/1.00仍漏标题29/下划线28。独立拒收，Accept NOT RUN |
| 新自然正向 | 900秒限时；含停止和控制核验902.63秒，26已完成模型记录，另1在途未知 | 独立v2合格9例、项目271过/1跳过、809旧完整行/严格范围过，仅改docs/usage.rst、added0、标题29/线29；仍EXECUTE，超时停止本次新进程后cancel。正式Review/Accept NOT RUN |

坏件Review的新快照包含原始请求/当前指导及627字符当前差异，31项来源判据，无section截断。它没有查阅历史，选择两个可执行检查并消费真实退出0/9例/项目结果后，结论仍声称全部内容、位置、样式、隔离与范围要求满足。其实际局部命令保留了28字符下划线的精确锚点，并未检查是否符合原始样式条件。不能从“真实检查通过”推出完整覆盖；也不以未查阅或工具数本身判错。goal_eval.requirement_coverage仍null/unassessed，模型结论没有被运行时认证为全面覆盖。

正向模型先生成交付并真实遇到示例输出失败，后续自行修复插入返回值的输出，最终独立产物合格；不是完全无修复能力。主要时间消耗在自拟方法反复误用解析/运行API及重试。原规划检查执行报AttributeError，替代方法中出现0项选择、错误参数/包装、先预设10项而实际9项等失败，stderr和stdout完整留在模型payload，不是反馈丢失；原要求没有固定10项或9项，不将计数当需求，不加入领域计数器或自动修复API用法。

### 三次方法修订为什么失败

通过的替代检查为新观察序号56（从0起），原方法真实失败为42。随后项目必需检查57通过；58又执行一个未登记run_command作旧行核验。该命令stat_only观察无变化，但任意shell不是可靠只读能力，commands_needing_execution仍按既有规则保守将其视为可能写入；替代证据因此陈旧。59、65两次完整原命令修订均按此拒绝。模型没有重新执行替代检查，不能绕过新鲜性检查接受旧绿灯。

64的引用模式请求使用了拼接错误、账本中不存在的failed_tool_call_id，返回Execution reference is missing or ambiguous；不是有效失败ID被丢失。通过ID确实存在，失败ID不能从两个相似记录拼接生成。全场0次成功修订、0次request_execution_permission、0个新DecisionPoint；没有清理授权或审批阻塞。拒绝事实和错误均在模型可消费观察中，不凭此宣称反馈已足够帮助收敛。

本刀不放宽新鲜性规则、不将stat无变化升级成任意shell只读认证，也不自动重跑/替换命令。下一刀先核实拒绝是否能提供当前真实失效观察、方法身份和可用精确引用，使模型选择新鲜复验；只在反向控制证实通用数据闭环断点后修复。原始要求的覆盖、有效替代与坏件漏检继续独立考核。

### 实际触发与计量

两场26条新run_command/run_tests命令均无here-document，冻结旧guard/lexer复判均不会拒绝；没有实际触发本刀literal边界。WSL工程测试证明该路径可执行，不能据正向产物合格宣称自然任务已验证其因果效果，也不能将本次超时归因于here-doc或Review索引。

两场共28条已完成MiniMax-M2.7记录（坏件2、正向26），已知1060980输入/20059输出token。正向被终止时另有1次未记录完成结果的模型尝试，cancel的durable_ledgers恢复保留27次模型预算，precision=conservative、unrecorded_model_attempts=1；合计29次保守尝试，未知用量/费用不伪装为0、不退预留、不签精确总费用。与原有4001预留是不同现场，原预留不动。

68个新工具调用/观察逐一关联、ID全局唯一，均dispatched/收费，50工具预算单位（坏件2、正向48）。旧坏件继承24模型/41工具和原始token前缀另计，不混入新量。方法三副本6次diagnostic_controller调用不属于模型自主执行或这68条产品账本。无新MCP/skill执行。原命令请求与实际requested_command字节一致，无自动改写。

final/closing/detail/timeline/stop审计已完成：冻结运行时、baseline、旧账本前缀/全部登记旧实验、上一坏件与paused here-doc现场hash均保持。新正向进程组已空；只取消本次达到预登记上限的新运行。所有旧DB/审批/运行状态、旧running/REVIEWED无进程现场及4001预留不动。未续跑/代批/执行旧pending；不重启已完成helper或无改重采。

## 交接边界

私有证据：~/.cache/asteria-evaluations/s131-heredoc-coverage-analysis-20261121的readonly-method-audit.json；s131-heredoc-20261121的registration、negative/positive-result、final/closing/detail/timeline/stop-audit。新工作副本s131-heredoc-negative与s131-heredoc-tables，冻结运行时s131-heredoc-eb71de8356ea287c55d01ea6c4c22cb7caa4f66c。日志保存在Windows临时目录asteria-s131-heredoc-*。这些私有现场、路由与本机记忆不入Git。

已更新计划§16.2/1.2.268–1.2.269、brief、当前状态、AGENTS指针、vibe及本机记忆；工程通过、产物合格与原生整链完成分开记录。下一步仍是方法新鲜性拒绝与精确引用的可消费反馈闭环，及Review对原始要求/有效替代的实际覆盖；不新开编排、不放宽授权、不自动改shell、不堆提示或打专用补丁。Verify禁用时NOT RUN，不启workflow/读key。S131尚未完成。
