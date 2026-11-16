# S131 — Review 当前产物实证与责任链修复

2026-11-16。仍属 S131；执行真源为总计划 §16.2，[brief](../../../benchmarks/reference_briefs/S131-content-preservation-contract.md)。前四轮编码试验见[原报告](S131-postfix-real-comparison-20261116.md)，其拒收、审批和计量不变。

## 结论与边界

旧版 Review 对两个真实缺陷均给出 pass/1.00，但实际模型调用为 **0**：这是确定性快捷通过绕过了语义评审，不是模型已看过却判断正确。修复当前产物输入、实际输出协议和不可用路由后，最终冻结 `74c7298` 的标准 Review 明确识别了短标题线和错章节/样式；两例均得到可消费的 partial。

**整组尚不能称验收通过。** 仅补足一个点的产物正控被认定内容、结构、功能全部正确，但最终整体仍 partial/0.93，理由是历史 pytest 缓存变化。这个正控只由独立 oracle 证明产物有效，并未证明全部历史过程满足每条模型扩展约束。原始用户要求“不得创建用户文件”，GoalSpec 另扩展了“验证不能修改编辑范围外任何文件”；运行时工作区快照又明确排除生成缓存。三者的范围及来源尚未在 Review 中充分对齐。不能把该结果直接算格式漏检，也不能未经澄清给缓存永久豁免或改写历史成通过。

本轮只执行已有 Review，没有重新执行编码目标，没有运行 Accept。负控原产物不改；正控的一字符修正只在独立评估副本发生。原 C/D 项目与账本完整哈希不变，全部 Review 副本的非运行时项目文件和工具账本也不变。

## 登记与对照

三例始终使用相同原始目标、原计划和原历史证据，独立 v4 在调用前核对 false/false/true；缺陷与 oracle 答案不进入模型提示。每版独立源码、工作区和快照，不改上一轮记录；每例外部 180 秒上限。运行默认实际路由 MiniMax-M2.7，无额外凭证读取或上传。

| 对照 | 来源及独立判据 | 基线 6eded2a | 最终 74c7298 |
| --- | --- | --- | --- |
| a：短标题线负控 | 原 D，26 字符标题/25 个点；产物无效 | pass/1.00，0 模型 | partial/0.93，明确指出少 1 字符；53.01 秒 |
| b：错章节/样式负控 | 原 C，新小节在 Handling Data 而非 Queries；产物无效 | pass/1.00，0 模型 | partial/0.68，明确指出位置和样式；23.54 秒 |
| c：产物正控 | D 的评估副本只补 1 个点；v4 的 10 示例通过 | pass/1.00，0 模型 | 产物认可，整体 partial/0.93，历史缓存范围疑义；56.76 秒 |

这是已知缺陷的后修复对照，不能外推未见任务、跨 provider、统计检出率或小时级自主能力。三轮修复各对应新证据暴露的通用责任缺口；所有中间结果保留，不反复跑同版挑绿。

## 已修复的责任链

`7b7517f` 删除 Review 按文件类型/任务完成率直接生成语义通过的分支及其专用辅助逻辑，复用既有 ReviewAgent。命令绿、任务 done 继续保留为执行事实，不能替代当前产物和原始要求的判断。

新增 `core/review_artifacts.py` 通过既有 ReadFileTool/PathGuard 有界读取当前声明产物：最多 16 文件、单文件 64 KiB、总渲染正文 192 KiB。受保护、缺失、部分或被省略文件显式留痕，不完整证据不能保留 full pass。读取显式覆盖默认 800 行分页，真实 830 行文档不会被悄悄截尾。快照经过 `review_artifacts` schema 验证，保存在各自 run 的唯一文件；模型调用和报告绑定相同 evidence_id/ref。SHA 指向实际渲染片段 UTF-8 内容，不冒充完整原文件字节哈希或防篡改签名。

模型被引导根据原始目标检查当前产物的要求、位置、结构、呈现与可观察结果；产物/旧工具输出作为不可信数据，不作为新指令。没有 RST/Python/provider 特判、领域验证器或新评审编排。缺模型、初始化失败、非 JSON、无合法 overall 判定均保留为 unavailable/partial，score=null；已有执行失败继续保留。不可用的下一步为重试 review，不误导 coder 重写已验证产物。

`abe5423` 把**实际 EvalReport schema**加入提示，而不是只提 schema 名；通过 SchemaValidator 的独立副本读取，缓存不会被调用方改写。旧 GoalSpec 的 prose target_outputs 复用已有具体文件判据，避免把“workflow evidence”当丢失文件；Task 显式路径仍按字面处理，包括含空格文件名。

`74c7298` 增加简洁报告指导及**最多一次**无效回答后的协议纠正。仍用原模型、5000 输出上限、既有调用预算及总评审时间保险；时间预算只控制是否启动下一次调用，不保证当前供应商请求在该时刻中止。反馈包含真实格式错误、finish_reason 和原响应片段，要求保留实质发现，不提供正确答案、不猜字段别名。无效响应保留最多 24000 字符及完整响应 SHA/长度/截断标记；纠正仍失败继续 unavailable，不得自动通过。最终三例均一次得到有效判定，纠正机制在真实最终样本中 **未触发**，仅有确定性回归证明。

## 中间真实结果不抹除

| 源码与轮次 | a 短标题线 | b 错章节 | c 产物正控 |
| --- | --- | --- | --- |
| 7b7517f 当前产物接通 | 正文 pass，未识别；顶层 status 不符合契约 | 正文指出真实错章节，但顶层 status 无法消费 | 正文认可，但顶层 status 无法消费 |
| abe5423 实际 schema | 5000 输出、finish_reason=length、无 JSON；不可用 | 有效 partial/0.72，识别章节/样式 | 有效 pass/0.99 |
| 74c7298 简洁报告/有界纠正 | 有效 partial，识别短线 | 有效 partial，识别章节/样式 | 认可产物，整体因历史缓存疑义 partial |

7b 的三例均为 unavailable；不能把“识别了但协议不可消费”写成完全通过。abe 的 a 只有 API success 与截断证据，不能冒充已识别。最终 c 是有模型判定的范围争议，与模型缺失/协议不可用不同，也不能借前一版 c 的 pass 给最终版本签字。

## 证据与计量

全部审计目录位于 WSL `~/.cache/asteria-evaluations/`，对应：

- `s131-review-probe-20261116`：基线，冻结 6eded2a。
- `s131-review-fix-20261116`：当前产物修复，冻结 7b7517f。
- `s131-review-contract-20261116`：实际 schema，冻结 abe5423。
- `s131-review-final-20261116`：简洁输出/有界纠正，冻结 74c7298。

每轮含 registration、三例 result/report、日志与快照；最终 `cross-round-immutability-audit.json` 追加核对全部副本项目文件/工具账本不变。原始 C/D 哈希（含原账本、排除生成缓存）也逐轮验证不变。新模型记录仅追加在副本，继承前缀保持；没有重编号历史工具观察。模型请求引用的快照与最终报告逐一关联，既有 cost_report 的新增调用数及输入/输出 token 与实际新记录精确吻合。

最终三例各新增 1 次 MiniMax-M2.7 调用，共 3 次、146393 输入/9706 输出 token；未触发模型工具动作，执行工具账本无新增，当前产物由运行时只读采集。与旧版 0 次模型的快捷通过相比，语义评审有真实推理成本。协议纠正最多再增加一次调用，并受原预算约束；本轮不估造货币费用或供应商账单结论。

## 验证与后续

最终源码 74c7298：WSL 相关 **78 passed / 52.52 秒**；Windows 协议回归 10 passed、此前相关 77 passed；最终 Windows 完整 **1963 passed / 5 skipped / 42 deselected（514.36 秒）**。Ruff 全仓和 mypy ratchet 无新增错误（60 已知/18 已不再报告，未更新基线）；五离线基准通过。

中间 abe5423 Windows 完整 1960 passed/5 skipped/42 deselected（436.29 秒）。第一轮全套曾暴露两个旧 fixture 假设：prose 产物被误作文件，以及无模型直接验收；已分别修采集兼容性和夹具的 partial→review 预期，原失败日志保留。不能把中间版本测试当最终版本签字。

公开 GitHub API 复查 Verify 为 `disabled_manually`；74c7298 无 Actions run/check-run，远端验证 **NOT RUN**，没有启用工作流、托管密钥或部署。

下一步仍保持 S131：先独立核实**原始用户要求、模型扩展约束、生成缓存与历史过程证据**的权威/范围关系，必要时补通用来源和范围事实；不按缓存名或文档格式强行判绿。已回代码核实 [workspace_snapshot](../../../src/asteria_runtime/core/workspace_snapshot.py) 的 `_SKIP_DIRS` 将生成缓存视为 authored-change 扫描噪声，但这个排除表只定义观察覆盖，并不是用户授权豁免。再登记一个独立新目标，用冻结 v4 和完整 Goal→Execute→Review 生命周期验证；仅独立验收合格才 Accept。不重跑同题挑绿，不扩大编排/强沙箱，不解除 shell 删除审批。

机制参考：[Anthropic 长任务 harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)强调用户需求与真实验证证据，[OpenAI harness engineering](https://openai.com/index/harness-engineering/)强调环境可观察性和反馈建设。这里借用原则，不声称对方采用本项目协议、快照字段或边界规则。

后续（2026-11-16）：[来源/完整流程核实](S131-source-scope-lifecycle-20261116.md)已执行：来源/扫描事实接通，旧正控通过但短线再漏检；新lookup范围失败，补自动收尾/Review显式边界保护。本文冻结结论不回填；新报告区分真实模型失败与0付费后修复回放。
