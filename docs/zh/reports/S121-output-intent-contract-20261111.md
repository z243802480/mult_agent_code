# S121：结构化产物意图与有界目标纠正

日期：2026-11-11。对应 [brief](../../../benchmarks/reference_briefs/S121-output-intent-contract.md)、总计划 §16.2 第 33 项。

## 结论

通用工程机制已落地：模型明确标注必需/可选/仅许可，规范化层经 schema 校验后投影必需产物；确定性规划不再从这类目标的自然语言里重新猜产物。随后补上一次有界 GoalSpec 格式/schema 纠正。

**真实新链路仍未验收。** 本轮一个新目标，286.64 秒：功能 oracle 11/11、旧 oracle 15/15、项目 273 项全过，四个交付物及严格编辑范围通过。但初始 GoalSpec 返回内容没有完整 JSON，走旧 fallback，typed 分类没有生效；原声明命令的导入条件又与实验预检不一致，native run 暂停。保持独立拒收，不重跑刷绿，不做正式 Review/Accept，不覆盖 S120 范围失败或 counts NOT RUN。

## 工程边界与验证

参考 [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 的明确结构/类型思路。本实现使用通用本地验证，不依赖某 provider 的 constrained decoding；结构合法不等于模型标注语义正确，仍需独立行为/范围审计。

- 新增可选 `output_intents`，元素含 value、obligation（required/optional/allowed）、可选 condition。路径和条件分开；完整意图保留，两个 schema 副本同步校验。旧字符串/path 对象兼容。
- canonical `target_outputs` 只取经验证的 required 原值。空值、未知标签、错误类型、required 携带未决条件都不能静默变成必需产物；原始用户目标不丢失。
- typed 目标的确定性回退规划使用 canonical 必需路径和已有 core 路径判据；保留合法中文/括号，防止从约束中重提可选路径或猜 README。旧目标保留兼容分支。
- GoalSpec 收到无效回复后，沿用 Planner 已有机制给一次有界纠正：同一 client、预算、元数据、原目标/上下文/权限，保持输出上限；提供验证错误、finish reason 和截断事实，要求完整简洁 JSON。只有 received-but-invalid 才纠正，transport/provider 失败不在此重试；两次仍无效时保留原安全 fallback。
- 不改 execute/run、路径解析器、权限门、默认预算、provider 或任务编排。没有删除条件措辞的规则，没有 Cache/TinyDB/模型名特判。

先红后绿：初始标签投影/校验 6 例红，最终相关 8 例过；有界纠正新增回归旧版 3 红 / transport 1 绿，修后均过。覆盖 schema 持久化→规划、条件不拼路径、仅许可不升为交付、保留 Unicode、无效数据安全回退、原请求与计量不变、有限次数和 transport 不重试。

首刀 `b6dd043`：Windows 完整 1752 / WSL 相关 102，Ruff/类型与离线基准过；精确 [Verify 43006166268](https://github.com/z243802480/mult_agent_code/actions/runs/43006166268) 三 job 全绿。协议恢复修正后 Windows/WSL 相关各 106、Ruff/类型通过；最终 Windows 完整 1756 passed / 3 skipped / 42 deselected（474.16 秒）已通过；最终生产提交 `6e3be93` 的 [Verify 43008738110](https://github.com/z243802480/mult_agent_code/actions/runs/43008738110) 三 job 全绿（Python 3.11、3.13、Studio），精确 head SHA 已核对。后续文档回执不改变产品代码；该 Verify 不证明 typed 真实链路或 keyed 模型路径。没有调整 mypy 的 60 条既有债务 baseline。

## 冻结新目标与入口勘误

新目标为 `Cache.select_items(predicate)`，不是重复 S117 的 peekmany。目录核对在任何调用/冻结前纠正了原选题。输入为 S116 已接受 cachetools 源码产物（MIT），复制不带旧 `.asteria`/缓存，原 S116 源码和状态未改；不是从干净上游重新解题。

目标、公约、检查器哈希在真实调用前登记并提交，执行器从 `b6dd043e6792915702f3e0d109812052a163080b` 仅导出 src/schemas。检查器采用公开接口、允许私有表示差异；11 方法 evaluator-only 正控制通过，使用 items()、造成访问副作用的反例 11 方法失败，另有 6 项判分器正反例。正控制只在隔离验证进程临时定义方法，未写模型源码或提供解题提示。

预检发现 resolver 实际选 native **harness/high_risk**，控制器原 session_agent 假设在 init 后、run 创建前被断言拦下，**0 模型调用**。调用前在 `4afa172` 留痕更正：沿用原目标/执行器/输入哈希和已预检工作区首次执行，不改词绕路、不强制或迁移 profile、不重做预检。不能把本轮称为 session_agent 证明。

原始证据：WSL `~/.cache/asteria-evaluations/s121-output-intents-20261111`；工作区 `~/.cache/asteria-workspaces/s121-cache-select`；run `run-20261111-0001`；冻结执行器 `~/.cache/asteria-runtimes/s121-b6dd043`。1800 秒外部上限未触发，没有增加预算、人工暂停、源码代修或答案提示。

## 真实结果与拒收原因

| 观察 | 实际结果 |
| --- | --- |
| 基线 | 新 API 缺失；旧 oracle 15/15、原项目 264 tests 过 |
| 最终公开功能 | selection 11/11、旧 peek 15/15、项目 273 tests（新增 9 项）过；导入绑定正确 |
| 文件 | 仅修改 src/cachetools/__init__.py、docs/index.rst；新增 docs/筛选（只读）.rst、tests/test_select_items_s121.py |
| 许可/可选文件 | keys.py 未改；未创建 _selection.py 或带条件注释的文件 |
| GoalSpec 真实分类 | 首轮输出 4000 tokens，解析无完整 JSON，fallback 后 output_intents 缺失、target_outputs=[]；不证明 typed 链路 |
| 原运行状态 | CLI exit 0，但 run paused / DECISION；不是目标完成或接受 |
| 独立总验收/正式评审 | 拒收；正式 Review/Accept NOT RUN |

36 次真实 MiniMax-M2.7 调用，输入 1,280,047 / 输出 29,632 tokens，逐项与 cost_report 一致，within_budget。源工作区/冻结执行器哈希未变。没有与其它不等价目标比较效率，也没有把后续工程修正当成本轮真实成功。

102 条**已记账工具记录**与 102 条观察同 ID、唯一；49 read_file、8 todo_write、8 search_text、6 apply_patch、14 run_tests、10 run_command、1 diff_workspace、3 list_files、2 write_file、1 find_files；其中 3 denied、12 failure。另外最后一条安装尝试在执行前被升级为 approval decision，不能混称这 102 条为全部尝试。人工审阅输入、patch 目标、可信来源 diff、文档和新增测试，未发现读取外部答案、执行器/安装包实现、其它实验或秘密。

任务 0001 完成；0002 完成文档/测试后，运行时执行原声明的两条命令得到导入失败；自动 replan 后 0002 discarded、0003 blocked。S119 的严格重验条件被实际接到修复任务（verified_noop_allowed=true，钉住原两条精确命令），但没有获得新鲜同身份通过，也没有实现零 diff 接受；pre_final 未闭合命令反馈没有触发。带 `exit 0` 的诊断包装命令成功不是原声明命令成功，当前任务仍暂停，不能据此声称通过。

模型最后提出 pip install，违反公约的“不安装”；权限门在执行前将其转为 decision，未执行。原冻结实验不申请批准该安装，也不放行或重置它。另有读取 setup.py/tox.ini/pyproject.toml 的范围拒绝，保留为实际恢复路径证据，不推断这些尝试都必要。

## 实验环境偏差与后续纠偏

本轮预检/外部检查额外设置 PYTHONPATH=workspace/src；实际 Runtime 父环境是冻结执行器的 src。冻结目标的普通 pytest 命令、Planner 的普通 import 命令没带项目源目录条件，导致实际导入失败。模型自身已经用 `-o pythonpath=src` 和显式源码绑定跑绿，但完成门按原声明身份重验仍失败。

这是**实验前置核对不充分**，不能归因于不会实现 API，也不应给 Runtime 加缓存仓库路径特判。以隔离 baseline 副本、真实 RunCommandTool（含 ShellGuard、环境净化和进程围栏）做零模型诊断：

- 控制器 src 环境下，两条普通命令都绿。
- 与 Runtime 父环境相同的 PYTHONPATH 下，普通 pytest 退出 2、普通 import 退出 1。
- 显式声明源目录的命令在两种环境均绿，baseline 源码哈希不变。

该诊断不是全任务 gateway 重放，也没有改变原 trial。它坐实预检环境不等价，不把修正后的诊断替换原声明失败。

下一项 S122：先在实际 guarded 环境验证公开命令/源码绑定及入口档位，再登记一个**新目标**检验有界 GoalSpec 纠正与 typed 规划的真实路径。禁止复跑 S121/S120 刷绿、偷偷修改冻结公约、增加 token 上限/预算、安装放行、语义猜词规则或新的编排 Wave。小时级、独立 provider 与 keyed CI 证明仍未完成。
