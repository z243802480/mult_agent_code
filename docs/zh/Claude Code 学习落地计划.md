# Claude Code 学习落地计划

## 1. 定位

本文把本地 `claude_code/` 源码学习结果转化为 Asteria 的可执行计划。它不是竞品复刻清单，也不是把 Asteria 改造成单体聊天 CLI；它服务于当前目标：构建本地优先、可恢复、可审计、成本受控的多智能体自治开发 Runtime OS。

`claude_code/` 目录仅作为本地参考源码，已加入 `.gitignore`，不进入 Asteria 仓库历史。

## 2. 核心吸收结论

从社区 Claude Code 源码中应吸收的精髓：

1. **Prompt 是产品内核的一等对象**：系统提示词不是散落在代码里的长字符串，而是由身份、任务原则、工具规则、风险动作、动态会话能力、memory、环境信息等 section 组装。
2. **工具和能力要对模型显式、对 runtime 受控**：模型需要知道 direct tools、deferred tools、MCP、skills、subagents、modes 的区别；runtime 继续强制权限、沙箱、预算、schema 和 evidence。
3. **工具优先级减少浪费和误用**：读文件、搜索、编辑、shell、子 agent 各有边界；简单定位不派 agent，shell 不替代安全文件工具。
4. **高爆炸半径动作必须独立建模**：删除、force push、改 CI/CD、外发消息、上传内容、读取 secrets 都应进入 DecisionPoint 或 policy gate。
5. **失败是 observation，不是终点**：失败后先诊断，再选择 repair、replan、ask、downgrade 或 stop；禁止盲目重试和制造绿色结果。
6. **delegation 需要高质量 brief**：给子 worker 的任务必须像交代新同事，包含目标、背景、已知事实、排除项、作用域、是否允许写入和期望输出。
7. **验证要独立于实现**：非平凡实现不能由实现者自封 PASS；ReviewAgent/MergeGate/Runtime OS gate 是 Asteria 应放大的优势。
8. **上下文压缩要保存继续执行所需状态**：ContextSnapshot 不只是摘要，还要保留目标、决策、文件触点、验证结果、失败证据、风险和下一步。
9. **用户进展是信任界面**：首次动作前说明意图，中途关键节点短更新，最终如实报告产物、验证和风险。

## 3. 必须保留的 Asteria 优势

学习 Claude Code 时不能丢掉这些核心设计：

- Runtime OS evidence-first：TaskGraph、WorkerInvocation、WorkerResult、TaskExecutionEvidence、RuntimeProfile、ContextMount、MergeGate 都必须继续落盘并可回放。
- 候选工作区与 promotion gate：并行 worker 和失败候选不能污染主工作区。
- 多模型、多 profile 调度：不能依赖单一 provider 或单一模型能力。
- JSON/JSONL MVP：SQLite 之前继续使用文件系统和 schema 校验的 JSON/JSONL。
- user_progress 主线 + Inspector 审计：用户看过程，维护者看证据。
- hard-stop DecisionPoint：预算、权限、产品方向和高风险动作必须可见、可决策、可恢复。
- 真实行为和测试优先：不接受 fake stub 冒充完成。

## 4. 文档收敛原则

后续中文文档分三层维护：

1. **主线事实入口**：`当前状态与路线.md`。只写当前阶段、已完成基线、主要差距、近期优先级和维护规则。
2. **长期设计主文档**：产品、架构、数据模型、工程化、治理、模型供应商、质量评估、运行命令、模型主导运行时设计、用户进展事件、Studio 产品与开发计划。
3. **历史/调研/复盘归档**：竞品调研、失败复盘、早期分册、已吸收的临时计划进入 `docs/zh/archive/`。归档文档可读但不作为当前实现依据。

原则：宁愿少而准，不要让用户和 agent 在二十多份主文档里找当前事实。

## 5. 落地计划

### P0：PromptEnvelope 产品化

目标：把系统级提示词从隐式字符串变成 Runtime OS 可审计对象。

任务：

- 新增 `PromptEnvelope` section 概念：`identity`、`operating_contract`、`project_guidance`、`capability_manifest`、`tool_policy`、`safety_envelope`、`failure_repair`、`delegation_contract`、`context_compaction`、`user_communication`。
- 每个 section 记录 `name`、`source`、`priority`、`cache_scope`、`token_estimate`、`content_hash`、`evidence_refs`。
- 动态 section 必须声明 cache break 原因，例如权限变化、MCP/skill 变化、budget 阈值、compaction/resume。
- Prompt evidence 默认保存 hash + 摘要，禁止 secrets/protected path 内容进入完整 prompt evidence。

验收：

- `/run` 的 evidence 中可以看到 prompt section 摘要和 capability manifest。
- acceptance gate 能检查 prompt envelope 是否包含项目规则、能力边界、权限/预算边界和失败处理规则。

### P0：CapabilityManifest 分层

目标：模型看得懂能力，runtime 控得住权限。

任务：

- 将能力分为 `direct_tools`、`deferred_tools`、`mcp_tools`、`skills`、`subagents`、`modes`、`verification`。
- 每项能力记录 `permission_state`、`sandbox_profile`、`read_scope`、`write_scope`、`cost_tier`、`observation_schema`。
- 对模型提示工具优先级：读/搜/改优先专用工具，shell 主要用于测试/build/git/无法表达的命令，subagent 用于广泛探索、独立实现、对抗审查或上下文隔离。

验收：

- Planner/Worker context 不再只看到内部 Python 类名，而看到用户可理解能力目录。
- 简单文件读取/符号搜索不会被计划成子 worker。

### P0：ToolObservation 统一

目标：每次工具调用都同时服务模型循环、用户进展和审计。

任务：

- 统一 observation：`summary`、`status`、`next_hint`、`error_class`、`artifact_refs`、`evidence_refs`、`user_progress_event_id`。
- raw stdout/stderr/diff/telemetry 进入 evidence；模型只接收任务相关、可继续推理的摘要。
- 工具失败进入 repair/replan/ask/stop 判断，不直接等同任务失败。

验收：

- 失败工具调用能被下一轮模型消费并产生修复动作。
- Studio 主线不展示裸 stdout，Inspector 可追溯完整证据。

### P0：DelegationContract 与 brief quality

目标：避免“把理解外包给子 worker”。

任务：

- WorkerInvocation 增加 delegation brief 字段：`goal`、`why`、`known_context`、`files_or_commands`、`constraints`、`allowed_writes`、`expected_output`、`verification_expectation`。
- 增加 brief quality 检查：缺少作用域、输出、权限或验证预期时不能启动高风险 worker。
- 并行 worker 默认使用 candidate workspace 或只读模式；写入汇总必须经过 MergeGate/promotion queue。

验收：

- 子 worker evidence 能解释它为什么存在、能改什么、预期交付什么。
- ReviewAgent 能汇总 child diff/conflict/release risk。

### P0：独立验证契约

目标：非平凡实现必须有独立验证或明确说明无法验证。

任务：

- 定义 non-trivial change：多文件编辑、API/后端/权限/数据模型/基础设施变更、候选合并、release gate 相关变更。
- 非平凡变更完成前触发 ReviewAgent 或 verification route；实现者不能自封 PASS。
- PASS 必须关联命令、输出、artifact 或 evidence；PARTIAL 必须说明未验证原因。

验收：

- final report 不允许在测试失败或未运行时声称通过。
- MergeGate/acceptance gate 能看到验证者和验证证据。

### P1：ContextSnapshot 升级

目标：压缩和恢复后仍能继续真实工作。

任务：

- ContextSnapshot 固化：目标、Definition of Done、已接受决策、活动任务、修改文件和原因、验证结果、失败和修复尝试、开放风险、下一步。
- compaction 后恢复能力 manifest、最近文件触点、失败 observation 和 pending decisions。
- 压缩摘要不能作为成功证明，只能作为继续执行状态。

验收：

- `/resume` 后能基于 snapshot 继续任务，而不是重新读全量历史或丢失失败原因。

### P1：文档与命令面收敛

目标：让 agent 和用户都能找到唯一当前事实。

任务：

- `文档导航.md` 只保留主动主文档和归档说明。
- 已被主文档吸收的竞品调研、失败复盘等移入 archive。
- `当前状态与路线.md` 顶部增加“Claude Code 学习后的执行主线”。
- `运行命令.md` 和 `命令暴露面收敛计划.md` 保持一致：普通用户入口少，内部命令不默认暴露。

验收：

- 新 agent 从 `AGENTS.md -> 当前状态与路线.md -> 文档导航.md` 能在 5 分钟内定位当前主线。

## 6. 不做清单

- 不复制 Claude Code 的品牌、文案或 provider 绑定。
- 不把 Asteria 改成 unrestricted agent chatroom。
- 不用远端控制、插件市场或 dashboard 替代核心 runtime loop。
- 不把所有内部命令暴露给最终用户。
- 不因为提示词变强就放松 schema、权限、预算、protected paths 和 gate。

## 7. 最近执行顺序

1. 文档层：更新 `文档导航.md`、`当前状态与路线.md`，归档已吸收文档。
2. 数据层：在 `数据模型.md` 增补 `PromptEnvelope`、`CapabilityManifest`、`ToolObservation`、`DelegationContract` 字段。
3. Runtime 层：实现 PromptEnvelope builder 和 manifest builder，先旁路记录 evidence，不一次性重写 `/run`。
4. Worker 层：增加 brief quality gate 和 ToolObservation 输出。
5. Gate 层：把 prompt envelope、delegation brief、独立验证证据纳入 acceptance/release gate。
