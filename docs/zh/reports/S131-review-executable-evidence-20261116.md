# S131：Review 自选可执行证据与权限边界

2026-11-16，工程冻结登记；真模型尚未运行，不能签漏检已修复。前置真源：[聚焦报告](S131-review-change-focus-20261116.md)。

核实：ReviewAgent原单报告请求无工具；CorrectnessEval的opt-in rerun只重放已有命令，且在原工作区执行。readonly task不约束shell；CandidateWorkspace默认复制可能含受保护文件、也可能选Git worktree，未直接使用其创建路径。

参考 [Codex review task](https://github.com/openai/codex/blob/main/codex-rs/core/src/tasks/review.rs) 的普通agent循环复用与能力限制，以及 [Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) 的模型选择、应用执行、真实结果回传。只借鉴机制，不复制实现。

实现：复用model_driven_turn、ToolExecutionGateway/Registry/RunTestsTool及同一个shared_goal预算。通用循环可选结构化终局回调/工具协议，默认编码协议不变；Review语义rubric、验证指导、EvalReport输出schema不改。FakeClient按purpose先分发Review，避免新循环metadata误选离线编码fixture，不是生产模型特判。模型自主选择read/list/glob/grep/run_tests(command)，中间工具回合后直接返回原EvalReport；未选检查就记录零工具，不强制特定验证器或添加领域规则。

工具惰性创建一次性过滤副本，最多10000文件/128MiB/50000遍历项，排除既有候选排除目录、protected路径、symlink/junction，保留执行权限。副本当前产物必须匹配Review快照；不promote，结束清理。副本已有输入被改、原输入变化、所选检查未执行/权限禁止等事实不能被pass覆盖。输入SHA、工具/观察ID、限制与终止原因通过review_validation schema持久化，绑定产物evidence_id。

权限：无write/patch/restore/MCP/skill/delegation/提权接口；ask_everything不自动执行工具。其它档仍走既有ShellGuard、环境清理、进程围栏、配置的sandbox_shell与硬禁止项；拒绝回传失败观察，不制造无法恢复的批准卡片。最多8模型调用/120秒总时限；命令最多60秒且截到剩余时间，剩余时间也不扩大角色单次deadline。沿用共享成本硬停，模型响应后再检查预算才执行；已执行工具后provider失败不换档重放。

**边界**：副本不是OS沙箱。任意解释器仍有本机执行环境能力，静态guard无法保证绝对路径/网络系统隔离，过滤与终态hash不是抗恶意进程证明。禁止宣称shell只读或原系统零副作用。旧--rerun原工作区行为保留、纠正只读措辞。依赖/排除文件缺失可导致失败，不能自动安装/提权；独立执行不自动等于需求覆盖或正确verifier。

工程验证：Windows相关83过/1个symlink创建不可用跳过，追加边界后最终新单元30过/1跳过；WSL前批74过。Ruff/类型无新增（60 known/18不再出现）/文档23/五基准过。第一次全套因补齐deadline截断主动中止（PID49960，review-tools-full.log为PARTIAL）；最终完整套件/最终WSL待结束。测试准备的默认策略夹具、Windows短路径、观察格式错误假设及默认ask档未显式授权问题已修，没降低断言目的。

实验预登记：冻结当前源码，旧真实坏件副本只Review一次、不Accept；同冻结名表目标只跑一次完整Goal→独立v2→Review→Accept，沿用13控/v1诊断/v2合法替代修正/32轮900秒，无oracle提示/外部干预/清理授权。原9b/e69漏检与e69正向成功保持，不无改重采样。真实结果、来源/身份/计费/范围对账、后续计划待结束追加。
