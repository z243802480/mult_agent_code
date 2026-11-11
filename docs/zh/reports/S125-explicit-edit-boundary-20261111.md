# S125：明确编辑边界工程验收与真实运行对账

2026-11-11；[brief](../../../benchmarks/reference_briefs/S125-explicit-edit-boundary.md)。

## 结论

**编辑边界工程通过验收；真实目标整体未验收，正式 Review/Accept 未执行。** 执行器 `9ba348ebbd7b2278a2ea3dc9fab5bf3e9ef7061d`。确定性回放、实际编辑工具、冷/暖任务及真实采样都确认了单文件编辑限制；最终文档也已通过独立检查。但首次执行技能时产生的观察与下一条本地工具复用了 ID，严格账本对账失败，原记录不补写、不重编号来刷绿。

两阶段分别保留：首轮 **231.40 秒、16 次真实 MiniMax-M2.7 调用**，边界正确但文档格式拒收；明确外部反馈后，普通 CLI 暖续作 **69.08 秒、新增 13 次模型调用**，同一 run 的文档修复完成。累计 **29 次**，输入 **754,254** / 输出 **20,423** tokens 精确对账，预算未提高或重置。不能称首轮自治成功，也不能把两段加上审计等待外推小时级可靠性。

## 工程改动

GoalSpec 可选 `edit_boundary={mode:open|restricted, paths:[...]}`，由模型理解用户明确的编辑限制；Runtime 验证结构和相对路径，不从关键词、产物列表或仓库目录猜授权。文件精确匹配，目录以 `/` 结尾；空 restricted 列表不授予写权限。命名产物不等于排他授权，开放目标仍保留原探索方式。

边界随任务持久化并与请求写范围取交集，session_agent 扩写、测试路径授权和后续范围扩大不能移除这个上限。读上下文独立保持；子任务、同 run 暖续作继承上限。实际写文件、多文件补丁和备份恢复在修改前检查，目录链接不能把许可目录重定向到未许可位置；merge gate 再检查真实变更。受限任务的 candidate 导出不再先滤掉越界文件而让合并看不见它们。没有改 execute/run/acceptance 栈或新增工具/编排 Wave。

新字段在根目录和包内 GoalSpec/Task schema 同步，持久化回归通过。旧有效 GoalSpec 缺字段仍按旧行为兼容，不能声称旧会话已有结构化限制；新提示要求显式给出。无法解析的 GoalSpec 在原两次纠正后回退时不授予写路径，不把丢失的边界猜成开放。任意 shell/MCP 副作用的强隔离不在该路径 guard 的保证内，现有 shell/秘密/网络权限独立保持。

参考 [OpenCode 的 edit/read/shell 资源分离](https://opencode.ai/docs/permissions/)及 [Codex-rs 的结构化权限模型](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs)，不复制产品格式或依赖某个 provider。

## 确定性与环境验证

S124 的原 GoalSpec/任务作为固定数据，在副本上明确注入用户已有的两文件限制作为受控 typed 投影；旧执行器仍加入 docs/tests/tinydb 等目录，新执行器最终只允许两份文档。它证明后处理责任已修，不冒充一次模型自然越界或旧模型理解能力比较。原 S124 数据及目录哈希不变。

Windows 完整 **1821 passed / 4 skipped / 42 deselected**，685.44 秒；WSL 相关 **170** 通过，最终边界套件 **36** 通过（含 Linux 目录链接用例）。Windows 同套件 **35 passed / 1 skipped**，跳过原因是本机不能创建测试目录链接。Ruff（src/tests）、类型债 ratchet（无新增、60 known）及五个离线基准通过。

产品提交的 [Verify 43047783380](https://github.com/z243802480/mult_agent_code/actions/runs/43047783380)：Python 3.11/3.13 完整 job 通过；Studio 浏览器依赖安装再次报 `Temporary failure resolving azure.archive.ubuntu.com`，UI skipped，整体 CI 为失败。没有跳过 UI 或顺手改 workflow，keyed proof 仍 NOT RUN。

## 首轮：边界正确，文档未通过

输入从已接受 S124 源码复制，不带 `.asteria`；新目标只允许编辑 usage，增补自包含 dry-run 例子，展示计数和存储前后相同。未给模型解法或 evaluator；公开 pytest 先经真实 RunCommandTool 在 Runtime 同环境通过。原文档缺新例子检查为红，evaluator 自有正控制为绿，输入与 src/schemas 在调用前冻结、提交 `9ba348e`。默认实际 session_agent，原预算权限，900 秒外部上限未触发。

实际 GoalSpec 为 restricted/usage，模型计划后处理后写范围也只有 usage。模型读实现/原测试后添加例子，所有其它源码/测试/配置和原输入目录哈希保持。项目 271 tests 通过，但它为使自建文本提取 exec 编译通过，移除了 RST code-block 声明、加入未标记的顶层 `if True:`。直接运行 Python 不能证明文档呈现正确；按 [RST 代码块与 doctest 规范](https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html#literal-blocks)，这已不再是常规代码块形式。未安装或运行 docutils/Sphinx，不能声称已渲染。

冻结 oracle 只识别 doctest，未识别新例子，因此不能把它的缺覆盖单独说成 API 语义错误，也不能把原有 9 条旧语句通过算成新例子已验证。首轮拒收，不正式 Review/Accept；原 oracle 和失败结果保留。

## 明确反馈后的同 run 暖续作

`67a9d54` 调用前登记外部反馈及新目标，要求修为常规自包含 doctest、实际执行文档，仍仅改 usage。完整首轮源码/状态快照、旧任务、账本前缀先冻结。此次是反馈辅助修复，不能替换首轮结论。

控制器最初漏传已有 `--continue-session`，误走冷入口后立即中止；额外 INIT 记录的完成模型调用和工具记录均为 0。失败日志保留，原源码和旧 run 账本未改。修正为已存在的 `--continue-session --session-id run-20261111-0001` 后执行同一反馈目标，不把该控制器错误算成暖路成功，也没有产品补丁。

暖续作成功追加 task-0002；旧任务全部字段不变，原 goal 原文、预算、编辑边界和账本前缀保留，无新增 GoalSpec/Planner 调用。只有 usage 的新例子变化，无其它文件增改；原首轮完整快照、S124 输入和冻结执行器哈希不变。累计模型计量 16→29、tokens 精确累加，反馈阶段单列 600 秒上限未触发。

独立执行实际文档：usage 整节 **16 次尝试/0 失败**、API 整节 **4/0**；再将新增例子隔离到空上下文，**11/0**，证明自包含。后者是重复核验同一例子，不是额外 11 个独立例子。项目仍 **271 passed / 1 skipped**。人工审查两阶段完整 diff、所有工具路径/命令和 6 次 patch 目标，未发现秘密、网络、evaluator 或执行器访问。模型提供给 diff_workspace 的 original 是叙述摘要，不能代替真实基线 diff；本报告的范围结论以独立原/新文件哈希为准。

## 最终拒收点与下一项

47 条本地调用、1 条独立 skill invocation 对应 48 条观察，budget.tool_calls=48；模型 tokens、调用数和工具预算均正确，**不是费用漏计或技能动作无出处**。但技能 `skill__retrospect` 与下一条 todo_write 同用 `toolcall-0023`，观察 ID 也都为 `tool-observation-toolcall-0023`。冲突已在首轮快照中，非暖续作新产生。

代码核实：gateway 与本地 record_tool_call 以本地调用文件长度分配 ID，成功 skill/MCP 分支走独立适配器账本，未推进同一个身份序列。因此本例跨通道身份不唯一，最终 source_qualified/independent_accepted 均为 false，正式 Review/Accept NOT RUN。不修改历史调用 ID 或添加一条伪造调用来通过对账。

**下一项 S126：跨通道工具身份唯一性。** 先用成功技能→本地工具的真实序列确定性复现，统一身份分配并保留各通道原有证据及预算责任；MCP 同分支需确定性回归，不能称已有真实 MCP 事故。验证失败、拒绝、冷/暖续作与累计计量，再做一个新真实目标；本次原失败留作历史，不重新编号旧账本。文档判分器对原生代码块及实际呈现的覆盖也仍待改进，不以更严 JSON 代替语义验证。

完整证据：WSL `~/.cache/asteria-evaluations/s125-edit-boundary-20261111`，含 `replay.json`、`phase1-result.json`、`phase1-workspace`、暖续作结果及 `ledger-identity-failure.json`；工作区 `~/.cache/asteria-workspaces/s125-doc-dry-run`。有效目标及暖续作均为 run-20261111-0001，额外 INIT 记录单列为控制器错误，不混算成第二个有效目标。
