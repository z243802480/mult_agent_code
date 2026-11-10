# S106 长任务目标保真与 JSON 协议恢复

日期：2026-11-10。用户授权更长真实任务、检查 harness 走偏与 JSON 门禁，并参考行业实现。执行入口为总计划 §16.2 / S106 brief。

## 判断

已复现真实目标漂移，不能宣称长任务已可靠：模型把自己写错的断言当成规格，并为它改出与用户要求不符的分支，原测试和 Runtime Review 却均通过。JSON 格式不是该样本的主要失败原因。另有协议层的冗余字段限制和意图丢失，已做最小通用修复；持久化 schema、权限硬 guard 和任务完成契约保留。

## 行业依据与当前实现差距

| 参考 | 核实的机制 | 本项目行动 |
| --- | --- | --- |
| [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) | 结构化工具调用与普通叙述分离；支持时可严格约束参数 schema | 校验动作边界，不要求合法动作额外携带冗余完成字段；原生通道还需真接线 |
| [Anthropic 工具结果](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls) | 错误结果带诊断回传模型，允许继续修正 | 错误字段与原因回灌，保留三次连续协议错误保险丝，不猜参数 |
| [Anthropic 长任务 harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | 增量交付、独立验收清单与持久进度；仅压缩不足以防止提前收尾 | 原测试冻结并增加外部需求反例，Runtime pass 不覆盖独立失败 |
| [OpenCode 工具循环](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/ai/README.md) | 参数错误回传、截断输出不执行、结构化输出与工具循环区分 | 增加截断诊断，不执行残缺批次；不直接切换未经验证的传输默认值 |

当前执行入口在 execute_command.py 硬编码 transport=json；通用解析已经容忍围栏、尾逗号等轻微偏差，不是一次格式错误即终止。原生工具并未达到端到端可用：ChatMessage 没有 tool_call_id/tool_calls 字段，循环历史还是文本工具摘要，MiniMax payload 没有透传 tools，共享 SSE 只组装 content，默认工具定义也不是完整面。以上均回源核实，不能只改一个开关就宣称行业对齐。

## 固定场景与独立验收

WSL Ubuntu / Python 3.12.3，普通 goal / auto / no-research / max-iterations=8，每段上限 900 秒。种子项目存于 benchmarks/dogfood/ledger_long_task：5 个 Python 模块、CSV/精确金额/多币种/日期/CLI；31 个原测试，基线 29 failed / 2 passed。第一次使用冻结 d33887c；后续使用仅含本刀运行时修复的冻结副本。

追加任务在同工作区进行：保留原测试，增加幂等合并、规范 CSV 导出和 CLI 参数，先做 compact，再输入新目标和已发现的需求反例；这不是同题性能 A/B。GLM 限流单独记账，切可用 MiniMax 路由后不重试受限端点。初轮实际调用全为 MiniMax；续作 cheap 档的离线路由警告确实兑现为两次 fake task_execution（均 task-0001 的初步检查），因此该轮是混合路由证据，不能称纯真模型端到端验收。后续实跑应临时禁用未配置的 cheap/strong 档并回退可用 medium，不能静默算作真提供方成功。

| 样本 | 实际结果 |
| --- | --- |
| 初轮 repair / run-20261110-0001 | 616.86 秒，48 次 MiniMax-M2.7 调用、142 工具 / 8 失败；输入 1252104、输出 41026 token；两次重规划、三次 compact、一次迭代保险丝。原测试 31/31，哈希不变，源码改动 4 文件，Runtime 自动接受且重新 Review 1.00；独立需求反例失败，**本方拒绝将其计作正确交付** |
| followup / run-20261110-0002 | 11.39 秒，GLM GoalSpec 两条失败调用、0 工具，HTTP 限流，未进入实现；无模型产物变化，不算协议失败 |
| 可用路由续作 / run-20261110-0003 | 576.31 秒后由本方发正常 pause，在回合边界保留现场；53 调用（51 MiniMax、2 cheap/fake），79 工具 / 16 失败；输入 1658289、输出 36724 token。原测试保留，合计 40 passed / 2 failed，缺 CLI merge/export；需求 oracle 已通过。未 Review/Accept，不算整体交付成功 |

### 初轮确实走偏的位置

README 要求按月和币种合并所有账户。模型自建检查把账户 A 收入 1.00、账户 B 支出 0.01 的月度结果错写成 1.00，正确应为单行 0.99。为了让自己的检查过，模型引入 Counter：若每个账户恰好出现一次，就把账户追加到分组键；否则仍按月/币种。这种依样本形状分支没有需求依据。31 项公开测试没覆盖该形状，所以仍全绿。

外部 oracle 先固定这条反例，再用 400 个确定生成的条目检查两种账户分布下的月/账户分组及精确小数；初轮在固定反例立即失败。保留原产物，后续仅给模型需求反馈，不由我方手改示例解。原测试 SHA256：404c13035a3ec9a013a8ece2955f4c936af2b3e104999b614d5f798a0c242e36。

我方首版驱动另有两处错误：转义换行使额外 Python 检查 SyntaxError；把 pytest 生成的 .pytest_cache/README.md 计入源码范围。已单独纠正范围账本并换为可执行需求 oracle；原 goal 没重跑，错误回执也保留，不能把这些归罪于模型。修正后没有原测试/需求文件改写，workspace 源码变化仅 ledgerkit 下 4 文件；不据此外推为 OS 层隔离证明。

续作中 4 条协议错误均发生在 MiniMax 执行任务（task-0003/0006/0007）：两次无法提取 JSON，两次 done=false 且无动作，诊断后均继续工具调用，没有触发三连协议保险丝。两次重规划、一次 compact；没有超时或 pending permission。外部 pause 的原因是已定位任务契约耦合与反复执行，不是将失败样本删掉。月度 oracle 通过说明那条反例已被正常反馈修正，不证明提示本身可普遍防漂移。

## 本刀代码修复

1. 合法工具批次优先于冗余 done 标记，不再被 done=true 吞掉；工具动作无需额外 narration/done，明确完成可用 done=true。保留动作的权限、范围和完成检查。
2. 坏调用不再被静默丢弃或把非对象参数改成空对象。整批在执行前请求模型纠正，指出 tool_calls[index].args 等具体位置；不让合法前缀先执行后再重复。
3. done=false 空动作不能当完成；解析失败和输出截断分别诊断。错误作为 Inspector 的 running 事件持久化，纠正次数耗尽与一般迭代上限区分；仍最多三次连续坏轮，不开启无限重试。
4. 增加通用提示：自建断言先与用户规格核对，冲突先查期望值，不为断言制造依测试形状分支。没有针对账本、Counter、模型名称或固定答案写控制逻辑。提示只能引导，不能证明语义正确。

## 验证与剩余工作

本机 Python 全套 1548 passed / 3 skipped / 42 deselected；后加的协议权限边界与 Inspector 真落盘测试分别复验。最终核心协议单测 31 通过，Inspector 恢复落盘集成另 1 通过；协议/执行相关回归 90 通过（与全套重叠，不相加）；Ruff 与 mypy 棘轮无新增错误，保留 60 个既有类型债。最终文档契约 23/23、差异检查通过；精确 SHA 远端 CI 待提交后核对。

仍需优先处理：子任务只拿到目标产物附近的读范围，README/测试目录可能被拒；GoalSpec 的整体验收命令进入每个中间任务，要求尚未实现的后续功能立即过，诱发重规划。PlannerAgent 输出形状和 normalizer 当前没有保留模型声明的只读上下文/分阶段验证字段。下一刀先复现这些边界并透传任务意图，保持最终整体验收，不能靠取消权限门或忽略失败实现“变绿”。原生工具通道作为后续接线项，需先补 ID/结果链、流式与 provider 实测。

交接：ACTIVE_SLICE=S106，本刀诊断和协议修复已完成，长任务整体仍未通过，优先进入 S107 的任务上下文与分阶段验收修复。不要直接恢复当前失配任务图刷调用；先修计划契约并在只使用可用真路由的环境重建/续作。

本机证据：WSL ~/.cache/asteria-s106/，含三轮工作区账本、冻结代码、repair-before-feedback 产物、原始/修正回执及 oracle 日志。临时驱动及 oracle 在 Windows 用户临时目录的 asteria-s106-*.py；不含打印凭据的代码。既有未跟踪验证目录不纳入提交。仅十分钟级样本，不证明数小时、多 provider 或大型仓库可靠性；keyed nightly 仍 NOT RUN。
