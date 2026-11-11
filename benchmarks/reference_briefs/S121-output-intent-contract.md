# S121 — 条件产物与编辑范围的结构化语义

2026-11-11 用户「继续下一项」，承接总计划 §16.2 第 33 项。已读 AGENTS、总计划 §6/§16.2、S120 brief/report 与 GoalSpec/Planner/完成契约。保留 S120 范围失败和 counts NOT RUN，不重跑旧目标。

## 参考与机制选择

[Anthropic 官方 structured outputs 文档](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)强调用明确的结构/类型约束下游数据。这里只学习显式语义槽与验证机制，不要求特定 provider 的 constrained decoding，也不把格式正确当语义正确。沿用现有本地 schema 校验、模型规划和原始用户公约。

S120 暴露的缺口是单一字符串数组混装交付、许可和条件。采用向后兼容的可选 `output_intents`：模型逐项给 `value`、`obligation=required|optional|allowed`、可选 `condition`，路径与说明分离。GoalSpec 规范化层校验此结构，只把 required 的原始 value 投影到既有 target_outputs；完整 intent 持久化并经两份 schema 校验供规划审阅。旧字符串/旧 path 对象仍兼容；未知标签或错误类型不得静默升为 required。无意图字段不按措辞猜语义。原始目标保留，Planner 可在用户范围内自主选择可选方案，不改变完成守卫/权限。

先用带条件/仅许可/合法 Unicode 路径的输入复现旧规范化误收，再实现通用标签投影、校验、错误安全回退与 prompt shape；测试经过真实 GoalSpec→持久化 schema→Planner 合同边界。不改 execute/run、provider、工具策略、路径解析、默认预算或编排。

开工回归额外坐实：旧确定性 Planner 会扫描自然语言重提路径，且其文件 regex 漏掉括号路径。新 typed GoalSpec 的回退分支直接使用 canonical required outputs 与已有 core 路径判据，不再从 prose 扩充产物；旧目标路径提取保留兼容。不是新增词表或路径解析器。

## 新真实目标与冻结验收

在 S116 已接受 cachetools 源码产物的独立副本中建立普通新 session（无旧 .asteria/缓存，原工作区不变），实现新的 Cache.select_items(predicate)：先取得公开 peekitems 所代表的有效项快照，再按其顺序对每项恰好调用一次 predicate(key, value)，将真值项组成新的 list[(key,value)]；保留值身份，异常原样传播。即使回调修改缓存，遍历集合和值仍来自调用前快照。API 自己不通过 __getitem__、不更新淘汰策略、不清理 TTL/TLRU 过期项，已有 API 保留。

必须产物：`src/cachetools/__init__.py`、`docs/index.rst`、`docs/筛选（只读）.rst`、NEW `tests/test_select_items_s121.py`。允许但不要求改 `src/cachetools/keys.py`；仅确有实现需要时可新建 `src/cachetools/_selection.py`。固定目标/公约明确其区别，不提供实现代码或工具导航。原所有测试、AGENTS/旧 TASK 和新公约不改；无安装、网络、参考答案、执行器/安装包源码、秘密、相邻实验、强制工具或人工暂停。

先实现并验证公开独立 oracle 的合法表示与反例，再冻结目标/公约/oracle/runtime 哈希并提交登记；首次真实调用后不改输入。新 API 基线必须红，原 pytest 与 S116 oracle 必须绿。独立检查只消费公开接口，不约束私有容器布局。验收同时检查固定行为、新/旧全测、源码绑定、严格文件集合、旧输入/执行器哈希、所有工具输入和唯一观察 ID、计量、结构化 intent/canonical target/任务产物的实际语义。模型错误标注仍可能发生，须如实记录，不能靠投影掩盖。

本轮一个真实目标、1800 秒外部上限，原预算不增加，不额外反复规划/重跑刷绿。仅独立与人工审计均过才正式 Review→Accept；失败保留原样本，有通用工程缺陷才确定性复现后窄修，不改模型解题产物。完整 Windows、WSL 相关、Ruff、mypy ratchet、精确产品提交 CI；更新唯一计划/索引/本机记忆。分钟级结果不证明小时级或独立 provider，keyed proof 保持 NOT RUN。

调用前勘误：目录核对发现 peekmany 已是 S117 的历史题目，因此在任何真实调用/输入冻结前改用未跑过的 select_items，避免重复旧题。

## 首次调用前冻结登记

本提交 src/schemas 为执行器候选，启动前登记精确 commit 与逐文件哈希。Windows/WSL 相关各 102 项通过，Ruff/类型无新增；oracle 全 11 方法 evaluator-only 正控制过，使用 items() 的访问副作用反例 11 方法失败；6 项判分器正反例过。旧规范化六例先红，新分类投影/安全回退八例过。公开输入 LF 字节冻结如下，任何真实调用后不修改：

- cachetools_select_items_contract_s121.md SHA256 bf84f2547c3d2bb108d15b9731f3d1aa015e212623d055eddb873071c9c4442e
- cachetools_select_items_goal_s121.txt SHA256 a8fd4b483aaf94cf6df5a314f43b42019687fa324403975e437773869d0f5985
- cachetools_select_items_oracle_s121.py.txt SHA256 673501ddd303f5de3efbeb48425e9b557ab70efcb7c1e7e35dbe5ff20caa5f7a
- cachetools_peek_oracle.py.txt SHA256 f06d1df37efa1b2a7cf7a1576b71a1ae6f6e25b03dbdbaca5bd4056907b0e10e

首次真实调用前，本地完整 1752 passed / 3 skipped / 42 deselected（520.58 秒），Windows/WSL 相关各 102，Ruff/类型与离线基准均过。真实样本尚未执行，不提前宣称语义或端到端通过。

## 入口预检勘误（仍为 0 模型调用）

`b6dd043` 导出的执行器已完成新 API 基线红、原 oracle/全套绿、检查器正反控制与 init，但默认 resolver 实际返回 harness/high_risk，控制器的 session_agent 预期断言阻止了启动；没有创建 run，也没有模型调用。不得通过删改目标词语、手改配置或强制 profile 绕开它。保留全部预检输入与哈希，按**原目标、原执行器、默认实际 harness 档位**从已初始化且无 run 的同一工作区首次执行；不重做预检、不重置模型预算、不算重跑目标。其它冻结行为/范围/语义标准不变。结果明确标为 native harness，不能声称 session_agent 已证明；此处更正调用前的入口假设，不改变原公约或通过标准。

## 真实调用暴露后的协议恢复窄修

固定执行器的 GoalSpec 首次调用输出 4000 tokens、返回内容没有完整 JSON；既有逻辑立即 fallback，output_intents 未进入本次真实链路。原目标继续执行并保留此事实，不能冒充 typed 端到端绿。本刀追加通用协议恢复：复用 Planner 已有模式，只有收到但格式/schema 无效的回复才给一次有界纠正，原目标/上下文/约束不变，同一 client/预算/输出上限计量；transport/provider 错误不重试，两次仍无效才原样安全 fallback。先确定性复现再改，不改冻结执行器或原工作区、不重跑目标刷绿；修后完整本地与精确 CI 另验。它不替模型判断产物义务。

## 真实样本后的实验环境审计

原预检/独立 oracle 通过 PYTHONPATH=workspace/src 绑定源码，但冻结目标的普通 pytest 命令与 Planner 的绑定命令没有声明此导入条件，实际 runtime 环境下失败。模型已自行用 pytest 的 pythonpath 选项跑绿 273 项，最终声明命令仍按原身份保持失败；它随后提出被公约禁止的 pip install，被权限门拦成 decision，未执行。实验环境前置核对不足，不能将此失败归因于模型不能实现 API或运行时不能恢复。保留原冻结输入/声明红命令及暂停状态，不修改目标补跑。后续新目标必须先在**实际 guarded 工具环境**中核对公开声明命令和源码绑定，不能用控制器额外环境覆盖冒充该预检；无仓库特判/隐式命令改写/安装放行。

## 收尾验证

最终 Windows 完整 1756 / WSL 相关 106，Ruff/类型与离线基准通过；`6e3be93` 的 [精确 Verify 43008738110](https://github.com/z243802480/mult_agent_code/actions/runs/43008738110) 三 job 全绿。真实样本仍独立拒收，详见 [S121 报告](../../docs/zh/reports/S121-output-intent-contract-20261111.md)。下一项总计划第 34 项，先修正新目标的环境预检再验证新链路，不补跑原目标。
