# S131：Review 自选可执行证据与权限边界

2026-11-16。**工程闭环已验，真实漏检与同目标长流程仍未收敛。** 当前实现源码为17723eeb281aea1b8ce21af8ee5136f5d24e98f6；本轮真实样本冻结4001ca0、额外能力控制冻结17723ee，不能混作同一次运行。前置真源：[上一轮聚焦报告](S131-review-change-focus-20261116.md)。

## 已核实并修复

原ReviewAgent仅请求EvalReport，没有工具；CorrectnessEval的opt-in rerun只重放已有命令，且在原工作区执行。readonly task只阻止文件写工具，不能把shell变成只读。CandidateWorkspace默认复制可能包含受保护文件，也可能选Git worktree，未直接复用其创建路径。

参考 [Codex review task](https://github.com/openai/codex/blob/main/codex-rs/core/src/tasks/review.rs) 的普通agent循环复用/能力限制，以及 [Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) 的模型选择、应用执行、真实结果回传。只借鉴机制，不复制实现。

实现复用model_driven_turn、ToolExecutionGateway/Registry/RunTestsTool与shared_goal预算。通用循环增加可选结构化终局回调/工具协议，默认编码协议不变；Review语义rubric、验证指导、EvalReport输出schema保持。FakeClient按purpose先分发Review，避免新循环metadata误选离线编码fixture，不是生产模型特判。

Review可自主选择read/list/glob/grep/run_tests(command)，中间工具回合后直接返回原EvalReport。没有强制某个检查器、认知阶段或领域格式规则；未选检查如实记录零工具。工具执行使用惰性、有界、受保护过滤的一次性项目副本，最多10000文件/128MiB/50000遍历项；排除既有候选排除目录、protected路径、symlink/junction，保留执行权限。副本当前产物必须匹配Review快照，不promote，结束清理。输入SHA、工具/观察ID、终止原因、限制通过review_validation schema持久化并绑定产物evidence_id。已复制输入变化、原输入变化、所选检查未执行/被禁止等事实不能被pass覆盖。

权限无write/patch/restore/MCP/skill/delegation/提权接口；ask_everything不自动执行工具。其它档仍走既有ShellGuard、环境清理、进程围栏、配置的sandbox_shell与硬禁止项；拒绝回传失败，不创建无恢复通道的批准卡片。最多8模型调用/120秒，命令最多60秒且截到剩余时间/原角色deadline；模型响应后再次检查预算才执行，已执行工具后provider失败不换档重放。新循环遗漏的旧review_fallback失败审计已补回。

预算红控坐实原Review仅from_report会漏过期成本快照以后的持久消耗、也未预留。改复用既有BudgetController.from_run恢复账本高水位并在调用前持久预留；生产ReviewCommand红绿回归证明下一调用前已有历史模型/工具数和本次预留。未新造预算系统、并发预算事务或独立repair台账。

**边界**：副本不是OS沙箱；任意解释器仍有本机执行环境能力，静态guard无法保证绝对路径/网络系统隔离，过滤/终态hash不是抗恶意进程证明。禁止宣称shell只读或原系统零副作用。旧--rerun原工作区行为保留并纠正只读措辞；依赖/排除文件缺失可能使检查失败，不能自动安装/提权。独立执行不自动等于需求覆盖或正确verifier。

## 实际验证结果

| 场景 | 冻结源码 | 实际结果 |
| --- | --- | --- |
| 原真实坏件不改，副本标准Review一次 | 4001ca0 | 16.41秒，1 MiniMax，102605入899出，仍pass.98 **漏检**；0工具/未创建副本，完整627字符diff/29条件及工具能力实际可见，无Accept。 |
| 同冻结名表目标完整流程一次 | 4001ca0 | 外部900秒上限后SIGTERM并cancel；含后续独立检查的记录903.53秒。64条成功MiniMax记录，另保留1条未落账预留尝试；独立v2拒收“未覆盖要求”，项目271过/1跳过，仅docs/usage.rst改变、无额外文件。正式Review/Accept **NOT RUN**。 |
| 构造的错误摘要能力控制 | 17723ee | 29.18秒，6模型/6工具，36928入2363出；自选读取及Python计算，实际SHA与交付不同，消费输出后fail.2，副本输入/原文件保持，无Accept。 |
| 构造的正确摘要能力控制 | 17723ee | 59.03秒，3模型/4工具，11862入2335出；自选sha256sum/cat/wc，消费输出后pass.95，原文件保持，无Accept。 |

后两例是512KiB不透明输入与摘要交付的**构造控制**，只证明真实模型可以自主调用/消费工具，不能替代原真实缺陷或正向整链。没有给计算命令提示或外部oracle。错误摘要控制的自选命令把换行写成字面反斜杠n，字节比较本身有瑕疵；真实摘要不同仍独立支持否决，不能签其checker完备。正确控制没有复用该错误命令。模型能用工具和模型会选充分检查是不同结论。

真实完整流程中两次revise_verification均被拒绝。0模型审计核实：登记原命令1100字符，请求original_command1104字符，**仅多了引号转义**，两次都不等于来源记录。来源守卫按原约束拒绝，不能直接认作权限误拦或自动规范化shell绕过。另观察到模型自定了示例数上限；本轮没有把它当用户要求、没有替模型修改方法/产物。后续应核实原命令引用、实际失败观察与修订入口的闭环，优先工程化证据引用，保持来源/授权守卫，不用格式专用补丁。

原坏件、先前正向成功、先前评估目录、冻结基线/runtime及已记录模型/工具前缀均保持；新观察ID/工具ID逐一关联，Review调用绑定本次快照。正向失败108工具记录/108关联观察，107收费/85加权单位，64模型记录但成本保留65次预留：中断中的1次实际用量未知，不补零、不删预留。四例合计新增**74条已记录模型调用、2719696入57741出，另1未落账预留尝试**；负控继承的24旧模型不重复算新调用。全部已记录模型为MiniMax-M2.7，没有跨provider/小时稳定性或成本改善的证明。

## 工程检查与保留失败

最终17723ee：Windows完整 **2040 passed / 7 skipped / 42 deselected，550.07秒**；WSL相关 **94 passed**；Windows恢复/新工具相关51过/1个symlink创建不可用跳过；Ruff、类型无新增（60 known/18不再出现）、文档23与5个离线基准通过。原完整2007通过是e69历史结果，不能与本轮混算。

过程记录保留：第一次full因deadline修复主动停（PID49960，PARTIAL）；第二次2038过但1红（缺review_fallback，512.96秒，非通过）；第三次因预算真修复主动停（PID53048，PARTIAL）；最终verified-full.log才是本轮全套通过。预检oracle控制首次因导入路径失败时零模型调用，修脚本后在完全相同数据上13控通过；不改目标/验收器。未重复无改采样，未授权清理旧DB/批准记录，未Accept坏件。

## 当前计划与证据位置

ACTIVE仍S131，不开新编排/强沙箱。**已交付**：Review工具选择/执行/反馈通路、权限限制、绑定证据、恢复预留与失败审计。**仍开**：旧真实坏件未选独立检查而漏检；同目标900秒仍未交付正确产物。下一步先核实方法来源引用/失败观察/修订执行闭环，以及评审证据充分性；必要时用稳定证据引用代替模型重写长命令，不放松授权、不自动重写shell、不堆提醒。再登记修后同目标验证，不能换更容易的题刷绿。e69历史正向成功保留，本轮失败不覆盖它，也不能借历史成功签本轮通过。

本机私有原始证据：~/.cache/asteria-evaluations/s131-review-executable-20261116（registration、negative-result、positive-result、两opaque子目录、method-reference-audit、final-audit）；工作区和冻结runtime详见registration。Windows日志在Temp的asteria-s131-review-tools-verified-full.log/-verified-wsl.log/-verified-benchmarks.log。公开仓库只存脱敏结论，不提交运行目录/本地路由/密钥/原始私有日志。Verify仍禁用，远端本轮NOT RUN；推送后按当前SHA再核对，不启用工作流、不借历史绿。
