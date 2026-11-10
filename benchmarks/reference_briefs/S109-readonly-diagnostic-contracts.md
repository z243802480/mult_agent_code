# S109 — 只读诊断证据契约与有界验证时限

用户 2026-11-10「继续下一步吧」，承接总计划 §16.2 的 S108 剩余实证卡点。先修契约，再验证；不把 S108 两次失败改成成功。

## 参考与范围

已读 AGENTS、总计划 §6/§16.2、S108 brief/report。一手机制：[Anthropic tool result/error](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls) 将工具错误作为对应调用的观察；[Codex-rs ToolOutput](https://github.com/openai/codex/blob/main/codex-rs/tools/src/tool_output.rs) 区分结果与日志投影。借鉴明确证据与失败回灌，不抄专有实现，不按模型/题目/报错字符串放行。

- 明确模型任务的只读文件证据：复用 verification_policy 增可选 readback_paths；仅只读 diagnostic/verification 使用，须有真实 read_file 的最新结果，必要时经同一网关补读。每个必需路径必须被实际读取，缺失/拒绝仍失败；读依赖不增加写权，不能以读取文件声称实现已修或诊断语义正确。
- 命令验收与回读验收都为空不能自动通过；无显式新契约的旧计划保持现有判据。声明为必须成功的命令失败/超时继续阻断（原有诊断 expected-failure 语义不扩大），探索性红仍反馈/留账，不悄悄改退出码或按错误词过滤。文件回读仍经 PathGuard/权限/预算，最近对同一路径的失败不能被旧成功遮盖。
- readonly diagnostic 的重规划保留 task_kind、空写范围、原只读证据/命令；沿用 S107 verification 的边界。不能为了过 brief gate 自动授写权；确需修实现须明确升级范围。
- 暴露既有 timeout_seconds 参数给模型（command 默认 60 秒、tests 默认 120 秒不变），可选 verification_policy.timeout_seconds 用于约定命令补跑，并在重规划保留。仅传递正整数，不静默改写命令、扩大默认值或发明新重试状态机。
- 限定到规划提示/归一化、任务 schema 双份、证据选择、网关失败路径归属、只读恢复、工具提示/原生 schema；execute 只做既有收尾接线，不宽泛重构。不新增维护命令、编排 Wave 或并行默认。

## 验收与停止

1. Red→Green：确定性真实网关测试复现诊断探索拒绝/超时后合法回读、必需回读缺失或拒绝、同路径绿后红、空证据、旧任务兼容；所有红原记录不变。
2. readonly diagnostic/replan 正反例通过实际 Execute→Replan→Execute；恢复失败仍阻断，源码和权限不扩大。
3. 工具参数从模型形状/原生 schema 到实际工具与自动验收透传，超时真实失败，schema 双份一致。预算硬闸和高危审批回归不回退。
4. 相关回归、完整测试、Ruff/类型棘轮、文档契约及精确代码 CI。随后冻结运行时，用隔离 WSL 普通 goal 做一次真实仓库目标（由模型自行拆分；若未拆出诊断，不冒称该样本证明了真实独立诊断流）；不人工改解答/追加提示，最多 60 分钟和默认全局预算。独立验收失败或安全/预算暂停均如实留账，不刷样本。

ACTIVE_SLICE=S109。契约与接线已通过本地回归和精确代码 c3d9192 的 Verify 三 job；真实重跑因读取现行执行器后改解答，被否决独立自主证明并正常暂停。固定独立检查 11/12，缺模型观察/原始观察的 model_tool_name 数据；别名仍在部分 progress 记录中，不能夸大成全链路来源丢失，也不在运行后改 oracle 刷绿。后续须预先明确字段契约/等价表示及实验禁止参考解答边界。小时级自主能力保持未验收，详见 S109 报告。


首轮实跑新增卡点：模型给出不存在的 docs/master-plan.md、docs/briefs/S109.md，显式必需回读正确阻断。已复核 ContextLoader.root_guidance 有真实 AGENTS 文本，但 PlanAgent._user_prompt 只喂 GoalSpec/40 路径列表，不喂该指导；总计划 §16 顶部 brief 指针也过期到 S107。允许窄修规划输入：将已加载、限长的 root_guidance 显式传给规划模型，并提示只把真实已知路径列为必需证据；不再扫盘、不硬编码本仓库路径、不替模型映射假路径。修正文档索引后，保留首轮正常暂停的失败，使用相同目标/历史快照/固定独立验收重新冻结一次。单独记轮间研发介入，不拼接零介入成功。


文件证据工具补验：本仓库总计划超过 500 KB；ReadFileTool 文案称大文件可用 offset/limit，实际在窗口处理之前用总文件 200 KB 上限拒绝，故窗口也不可用。允许窄修 file_tools.ReadFileTool 的大文件路径：流式、受原 max_bytes 和行数约束地回读，未知总行数如实标记，不整文件装入内存；小文件行为不改、PathGuard 不改。用通用大文件/长行/多字节/分页回归证明，不按总计划文件名豁免。原生工具 schema 暴露已有 offset/limit，避免能力只存在 Python 接口。
