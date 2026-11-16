# S131：验证覆盖与预算来源核实

> 后续状态见 [Review 改动聚焦/正向完整流程报告](S131-review-change-focus-20261116.md)（1.2.236–1.2.237）。本报告保留覆盖/预算来源阶段快照；当前正向整链已通过，但旧负控漏检不变。

日期：2026-11-16。执行真源：研发总计划 §16.2 / S131 brief。修复源码：`f5be13c34e22b1031314b045990374769c8d1978`。前次 [有界反馈/授权报告](S131-bounded-verification-loop-20261116.md) 保留为历史快照。

## 核实结果

上一轮原始请求、GoalSpec 和任务 acceptance 都含结构、展示与保留要求，实际执行提示也收到这些字段。不能将短标题线误归因为丢失用户要求。

真正的覆盖偏差是：规划器自拟的选择器要求两次调用出现在同一个 doctest，未经可行性验证便列为完成检查；执行者为了让该检查通过，把原例合并成单行。这个行为检查没有覆盖结构和呈现。命令绿及完整项目测试通过均不证明原始全部验收条件成立。冻结产物仍有 29 字符标题 / 28 个点的真实缺陷，本次不手工补点，不改写旧拒收。

预算有确切的生产者错误：旧 RuntimeProfileBuilder 用 role 的单次调用数作为 worker 总调用额度，用 allowed_tools 的长度作为工具额度，并将 provider 单次超时换算成 worker 总运行分钟。旧实际 profile 因此记录 **1 模型 / 16 工具 / 3 分钟**；实际执行使用共享 BudgetController，并非这三项伪额度。

旧 GoalSpec 的 8 iterations / 60 model calls 是模型提议，不能自动覆盖运行策略。旧运行有 **25 次 task_execution 模型调用、1 次外层调度迭代**，二者不是同一个计量单位。只读审计时当前有效 `autonomous_long_task` 为 200 模型、1000 加权工具单位、32 外层迭代，压力为 within_budget；这不能补签历史 CLI 或证明过去从未改变策略。前次 Review 的预算指控不应直接当成已验证超限。

零新增模型的来源审计保存在 WSL `~/.cache/asteria-evaluations/s131-coverage-budget-audit-20261116/source-budget-audit.json`，含旧目标、计划、报告、模型/工具/skill 账本及产物摘要；原件保持不变。

## 通用修复

- 共享验证指导要求把原始行为、结构、位置、呈现与保留条件分别对应到当前证据；行为检查不替代其他条件。未验证的选择器、命名、数量或 setup 假设不是用户要求，不能为了让它通过反向改变合法产物。方法有问题时仍走既有修订工具，原用户/项目检查和要求保持。
- RuntimeProfile 的预算改用实际 BudgetController 捕获的额度，缺控制器时复用 `resolve_budget_limits`；明确 `shared_goal`、来源及 `weighted_tool_budget_units`。未知值保留 null，不从工具种类数或 role 调用数臆造额度；没有真实 worker 生命周期限制时不再记录 provider 超时折算值。
- 执行模型收到同源 runtime_budget。Review 在 schema 验证、来源绑定的当前产物快照中收到有效额度、压力、来源、单位、`current_review_start` 时间范围和实际记录的外层迭代数；没有外层记录就保留未知。旧 profile 和模型预算仍保留，不补签为真实执行额度。
- Review 指导要求任何预算指控同时给出适用限额、权威来源、同单位用量和时间范围。当前快照不还原历史 CLI，模型提议及 per-call hints 不成为新的 worker cap。配置字段本身也不证明每个轴都有独立执法；快照明确只以现有 BudgetController 压力轴解释压力。

持久对象继续过 schema；根目录和内置的 RuntimeProfile、AgentRunGraph、ReviewArtifacts schema 镜像同步。预算、权限、硬停、旧失败和显式范围验收保护不放宽；没有新增必须填写的验证 JSON、评审 FSM、格式解析器、自动清理或 provider 补丁。

机制参考：[Anthropic 长任务 harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) 区分需求清单与实际验证；[OpenAI harness 工程](https://openai.com/index/harness-engineering/) 强调将环境事实和反馈提供给 agent。只借公开机制，不宣称采用相同内部实现。

## 工程验证

Windows / WSL 相关各 **40 项通过**，涵盖有效 profile 覆盖原始预算、控制器捕获值、加权单位、未知预算、provider deadline 与 worker 总额的区别、原预算硬停、真实执行提示、Review 输入/持久快照绑定及授权完整回归。追加 Review 时间范围字段后，Windows 相关及文档 **25 项通过**，WSL 相关 **2 项通过**。Ruff 全仓和 mypy ratchet 无新增错误，类型基线未更新。

最终 Windows 全量 **1991 passed / 5 skipped / 42 deselected，483.94 秒**；五个离线基准通过。Ruff 全仓、mypy ratchet 无新增（60 已知 / 18 已不再报告，未更新基线）、文档契约通过。源码及 schema 冻结后未改，没有把测试绿当成真实产物合格。

公开 GitHub API 核实源码 Verify 为 disabled_manually，0 workflow run / 0 check-run；远端 **NOT RUN**，未开启 keyed 工作流或推送凭证。

## 修复后完整流程登记

仅在上述真实源码修复后复验一次同一名表目标，明确为有修复的同题对照，不称新任务。新工作区、运行时、原始目标、通用 AGENTS、项目基线和独立判据在调用前冻结；目标/指导与前次逐字节一致，32 iterations / 900 秒外部保险不改。

以已提交的名表 oracle v2 作独立验收，原 v1 留作诊断，不在运行后放宽条件。原 v1 的 9 控及 v2 的 13 控全部通过；合法单例多输出、逐条/批量方案均可，错结果、短线、错章节、表混杂、旧行变化和漏展示等负控仍拒绝。评估器在模型工作区外，不提示标题长度或答案，不中途改产物/预算/命令、审批清理或另换简单题。

预登记顺序：独立示例、完整项目测试、旧行/范围、身份/用量/来源全部合格后才标准 Review 一次；只有工程保护后的 pass 才复用新鲜报告执行 Accept。失败保留，不继续无改采样。

WSL 工作区：`~/.cache/asteria-workspaces/s131-coverage-budget-tables`；证据根：`~/.cache/asteria-evaluations/s131-coverage-budget-tables-20261116`；冻结运行时：`~/.cache/asteria-runtimes/s131-coverage-budget-tables-f5be13c34e22b1031314b045990374769c8d1978`。

## 真实结果：方法修订成功，整体仍拒收

单次原生 Goal **253.72 秒 / 23 次 MiniMax-M2.7**，completed / phase=ACCEPTED。多行示例的行为正确；独立完整项目检查 **271 passed / 1 skipped**，仅新增 docs/usage.rst 中的一块内容，所有旧行保持，无额外用户文件。原生自动接受不等于独立验收，原终态单独冻结保留。

本次实际使用 **1 次成功的 revise_verification**。规划器的表达式没有接受项目实际使用的相邻小节样式，模型执行后获得真实失败，再运行更正后的有界检查并调用修订工具；原失败观察和原必跑完整 pytest 保留。最终示例按原有多行结构呈现，没有被合并成单行。方法修订的 coverage 解释仍是模型主张，工具成功不等于其语义等价性已被独立证明。

独立 v2 判据仍因 **29 字符标题 / 28 个点** 拒收。另以实际新增行的唯一插入区间进行零模型、有界独立执行，**9/9 doctest** 通过；没有执行旧示例，也没有改真实文件。这个分离证明行为正确、结构仍不合格，不能用行为检查冲销结构缺陷。

为核实新预算事实在真实评审中的消费，追加预登记一次标准 Review 负控，模型只收到正常当前产物与运行证据，没有缺陷答案。实际 **20.98 秒 / 1 次 MiniMax**，98628 输入 / 1678 输出 token，返回 **pass / 0.98** 并称当前呈现正确，**真实漏检**。新鲜绑定快照明确 200 模型 / 1000 加权工具单位、within_budget、外层 1 迭代；本次没有再次提出旧的伪 worker 限额指控，但单例不能证明预算语义永远不误判。

Review 没有可执行 follow-up，因此按事先协议不创建人为修复任务，不启动 Resume，不把工程师知道的标题答案塞回模型，不追加同题抽样。**显式 Accept 未运行；真模型正向 Goal→Review→Accept 仍未通过。** 原生自动 ACCEPTED、Review 模型 pass、独立拒收三个事实分别保留，绝不将前两者拼成成功交付。

累计 **24 次实际 MiniMax / 791855 输入 / 21362 输出 token**；**41 本地工具 / 41 唯一关联观察 / 41 收费 / 24 加权单位**，0 skill / MCP。模型 ID、工具 ID、token、预算和来源均对账；GoalSpec proposal_origin verified、content_preservation 实际提出。原 9d 样本/账本/产物、源项目、fixture、冻结 runtime 和本次项目/Review 前工具及模型前缀保持。新运行真实 profile 已记录共享额度，不再出现伪 1/16/3。

实际主动授权和范围事件反馈均 **0 次**，未发生相应事件；不能声称真模型本次用了这两个入口。完整正向授权→恢复→验证→Review→Accept 的生产命令回归在本次两端 40 项及最终全量中继续通过，使用确定性模型与真实工具，不能替代真实模型正向交付证明。

主证据根保留 registration、v1/v2 冻结输入及控制、原生终态、原 final-result 拒收、negative-review-registration/report/result、final-lifecycle-audit、bounded-example-and-method-audit。原始 final-result 中正式 Review=NOT RUN 不改写；之后额外负控的结果另存。run_id 与旧工作区可能同名，引用时必须带工作区。

## 当前限制

指导和事实接线不保证模型对每项语义/呈现要求永不漏检；通用 harness 也不应猜文档规则来代替模型。一次样本不能证明统计稳定性、跨 provider 或小时级自主能力。原失败、DB、审批与在途预留计量继续保留；没有强沙箱、新编排或无真实摩擦证据的 Studio 功能。

下一项保持 S131：核实现有 Review 对当前改动和逐项要求证据的聚焦，优先复用现有变更/备份/来源事实；明确“模型宣称覆盖”与“有独立证据”的区别，不继续只堆通用提醒。先做不含领域规则的分离控制，找到确切的输入/证据缺口再实施；无明确机制变化不重复付费采样，不用文档格式或 provider 特判替代语义验证。
