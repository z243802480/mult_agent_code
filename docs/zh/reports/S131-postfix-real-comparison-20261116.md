# S131 — 真模型对照、接线修复与独立验收

2026-11-16。执行入口仍为总计划 §16.2；[brief](../../../benchmarks/reference_briefs/S131-content-preservation-contract.md)。本报告区分工程回归、真实契约提出、最终完成闸和独立产物验收。原 S130 拒收及冻结 oracle 不改。

## 试验登记与边界

四轮均使用 S130 查询文档原题、已接受 S124 干净项目副本及独立 oracle（A/B/C 用 S131v2，D 用冻结 v3）。每轮冻结独立源码、目标和评估器哈希；评估器位于模型工作区外，执行前验证原文负控、271 项项目测试、合法新增例正控及错误输出负控。默认实际路由 MiniMax-M2.7，auto 权限、session_agent、32 iterations、原策略预算、关闭研究，外部 900 秒上限。每个工作区中的 run_id 恰好相同，不代表同一运行；必须连同工作区识别。

这是已知失败背景下的逐版后修复验证，不是未见任务、不构成成对因果或成本下降证明。没有给模型提供独立 oracle 答案、人工修改模型工作区产物、批准清理或放宽检查；失败样本及其权限记录保留。

| 轮次 | 冻结源码 | 原生结果 | 独立验收 | 模型完成记录 / 输入 / 输出 token |
| --- | --- | --- | --- | --- |
| A：初版契约 | `9a0cb3ec032145d40131cb669dec30535a4f1227` | 900.54 秒外部终止，随后 Cancel 收尾为 cancelled | **REJECTED**：无约束/快照，110 原例加 SKIP，3 个 DB 遗留 | 62 / 2,024,270 / 58,689 |
| B：输出模板修复 | `553d5f73f1b30728016ad9dd1e1031702f40f82d` | 133.92 秒原生 paused，删除审批待决 | **REJECTED**：已生成约束/快照，但 3 处插入返回值未显示，3 个 DB 遗留 | 17 / 422,318 / 10,149 |
| C：工作目录事实修复 | `f3278a1ce1eab3f48a42441860a102ce00a8bda1` | 303.78 秒原生 completed | **REJECTED**：原行保持、无额外用户文件，但新小节放错章节且样式偏离 | 28 / 827,705 / 19,233 |
| D：指导/来源修复及 v3 | `2313ff7764aa87cf9702b48ab1f459522519e6a4` | 206.10 秒原生 completed | **REJECTED**：方法修订真实采用，仍有标题宽度缺陷；原评估器还误执行旧例 | 19 / 505,379 / 17,770 |

## 已修复的真实责任链

A 的 GoalSpec 在文字要求中保留了“既有内容不得修改”，却没有生成 `content_preservation`。系统提示介绍了字段，用户提示要求返回 exact JSON shape，却在模板中漏了字段。`553d5f7` 补齐模板和通用填写说明；不从自然语言关键词强制推断要求，不修改旧目标，也不把可选字段改成旧数据必填。两项回归分别验证真实 generate 请求可提出新字段、旧响应缺字段仍一次调用兼容。B 已实际提出约束并捕获源快照，证明该前缀链路接通；B 没有到最终完成闸，不能称已证明真实拒绝损坏内容。

B 的规划又把 Python 所在目录当成项目目录，为两条检查加了错误 `cd`。后来执行模型自行改目录，未替换原声明检查。运行环境函数已有 root 入参却未向模型提供实际命令 cwd；GoalSpec/Plan 更未接入 root 事实。`f3278a1` 由 ContextLoader 提供实际 `run_command_working_directory`，目标理解、规划与执行复用，隔离专家覆盖为自身 candidate root；未知 root 不猜测。两项回归验证进程 cwd 与工作区不同、父工作区与专家挂载目录不同的事实。没有按语言、provider 或报错文本改写模型命令。

## 仍需保留的失败含义

A 两次提出仅执行新增小节的验证替换，均被 `revise_verification` 拒绝。原始用户只指定完整 pytest；整份文档 doctest 是模型写入 GoalSpec.verification_strategy 的方法。旧 `method_provenance` 将整个 GoalSpec 文字纳入不可修订权威，导致模型方法与用户/项目硬要求混为一层，与 Planner“未验证 GoalSpec 命令只是建议”的指导矛盾。修复见下文；没有给旧 A 运行补来源或追认修订。

B 运行整份旧文档产生 DB 文件，随后请求 `rm -f` 清理；常开破坏性 shell guard 正确要求审批。评估没有批准。缺失 doctest 输出、选择不合适的验证范围、未履行原声明检查均未解决；权限暂停不是成功。A 还有删除拒绝后 shell 向 `/tmp` 搬移的成功记录，继续作为独立权限边界问题，不能以最终工作区干净替代过程守界，更不能声称 S131 内容完成闸已经拦截该通道。

C 的契约/源快照真实存在，最终 `contract_check.ok=true`、2/2 声明检查通过，且旧行确实未变。这证明正向完成路径被实际消费，不是新内容语义已被证明；真实损坏旧行的拒绝仍以此前工程负控为据。模型先执行补全标题字符范围的修正检查，又为让原声明命令通过，把标题改成波浪线、把小节从 Queries 移到 Handling Data。没有调用修订工具；本轮原方法本来就在 revisable_commands 中，所以仅修 A 的来源归属不足以证明能解决 C。

独立 oracle 对 C 的原样产物拒收有效，但层级覆盖仍有洞：v2 只检查 Queries 出现在标题之前，未检查小节位于该章节结束之前。另在评估目录建副本，仅修新标题的下划线后，即使位置仍错，原 v2 会接受 10 个正确输出示例。`hierarchy-audit.json` 保留该反例，原模型工作区和冻结 v2 均不改。下一采样前须冻结新的章节范围判据，并加入“正确示例但错章节”负控；不能把原 v2 的通过外推为层级正确。

## 末次工程修复：指导与方法来源

源码 `c7518653f5e8b39241d5170b06c1e37478f65418`：共享验证覆盖/方法修订指导原来只挂 GoalSpec、Plan 和旧 AgentHarness；实际 `model_driven_turn` 直接消费 Execute 系统提示，未收到该指导。现将同一份指导接入实际执行系统提示；实际 Plan→Execute 回归截获模型请求验证收到内容，不叠加 Python、标题或报错词专用规则。

新 GoalSpec 在 runtime 归一化时生成 `verification_strategy_origin`，绑定生产者、goal_id、原始用户文字和 strategy 摘要，覆盖 provider 返回的来源标签；缺/坏/变更记录仍按旧保守规则。来源有效时，仅模型提出的方法可进入既有修订资格；原始用户、其他硬要求、完整项目指导、配置检查与包装命令继续受保护。记录是受信 runtime 持久对象的来源绑定，不是防恶意磁盘篡改的签名。

修订仍要求当前任务、原失败→随后真实零退出更正、无工作区副作用、证据未过期、覆盖说明和原权威未变化，旧失败/原目标不抹除。14 项新回归覆盖来源伪标签、失配/缺失、用户/项目/指导与包装保护，以及真实失败→通过→修订工具写回；相关 Windows/WSL 各 86 项通过。生产函数对 A 原提议的副本反事实重放：旧来源无可修订项，新生产者归一化后仅新增 doctest 方法可修，用户 pytest 仍不可修；旧 run 原字节不变、0 付费模型调用。证据为 `s131-method-source-repair-20261116/production-method-replay.json`，不能称 A 当时采用修复或新真模型通过。

这两条接线修复后已另登记第四轮 D，仍用原题/预算、不向模型反馈评估器答案；D 真实采用方法修订，但未整体验收。不能据单次采样声称修复导致因果改善。

## 第四轮：真实修订采用与独立判据再审计

D 冻结源码 `2313ff7`，runtime 与 `c751865` 相同；另含 v3 判据及用户检查 fixture 纠正。原始用户文字与前三轮完全一致，206.10 秒原生 completed。模型保留原检查失败，执行零退出更正后真实调用 `revise_verification` 成功，任务声明方法与证据引用持久化；原用户 pytest 不变、原目标/来源摘要吻合，旧失败不删除。`verification-method-adoption.json` 绑定两个实际观察，补上此前未观察到的真实采用证据，不冒充成对因果结果。

新示例位于正确 Queries 章节，插入/计数/存在性/存量输出正确，旧行与范围保持。但 ASCII 标题有26字符，下划线只有25个点；RST 标题线须覆盖标题宽度，依照 [Docutils 官方 Sections 规范](https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html#sections)判定该格式缺陷，未人工修正原产物。

冻结 v3 还有独立错误：它把新增示例后未改变的 Queries 引言与旧展示例纳入执行，产生与新功能无关的失败。新增 v4 单独修判据：保留章节上界，核对固定 ASCII 标题宽度，用原行差异只选择新加的完整 doctest，混合旧 source/新 want 拒收；不把路径/RST规则塞入通用 harness。17 个控制包含合法批量/逐条/变量替代、插在既有引言前、错章节、短标题线、错误输出、旧行变化、旧例被加新输出、谓词收窄/放宽。合法引言前插入 v3拒收/v4通过，坐实误判；D 原样 v4仍拒收，只有评估目录副本补足1个点才通过10例。原工作区、冻结 v3 和原拒收结果均不改，不称原始试验通过。证据：`s131-oracle-v4-20261116/oracle-controls.json`。

没有第五轮付费目标；v4 的前瞻真实验证 **NOT RUN**。四轮正式 Review/Accept 都未执行，真实格式缺陷保留作下一步现有 Review 的只读负控，先查证能力再决定修复，避免继续为模型单次疏漏叠专用补丁。

## 对账与证据

A：148 次本地调用、148 个唯一关联 observation，147 次收费、114 单位，0 skill/MCP；工具计量与 token 汇总一致。cost_report 的 63 次模型计数包含 62 个完成记录和 1 个终止时未写回的在途预留，`accounting_recovery.precision=conservative` 明示保留；原自动检查的 `models=false` 留存，不改账翻绿。B：17 模型、22 本地调用/22 唯一关联 observation、22 收费/17 单位，0 skill/MCP，计量一致。上述都是本地记录与保守预留对账，不是 provider 账单证明。

C：28 模型、38 本地调用/38 唯一关联 observation、38 收费/37 单位，0 skill/MCP，计量与 token 汇总一致。仅 docs/usage.rst 新整行增加，无额外用户文件；原项目及冻结 runtime 哈希不变。过程未观察到清理或外搬移，不能据此称全通道隔离已实现。

D：19 模型、32 本地调用/32 唯一关联 observation、32 收费/25 单位，0 skill/MCP，计量与 token 汇总一致，源项目/runtime 哈希不变。

WSL 证据目录均在 `~/.cache/asteria-evaluations/`：A 为 `s131-postfix-query-20261116`，B 为 `s131-shape-fix-query-20261116`，C 为 `s131-workspace-facts-query-20261116`，D 为 `s131-closing-v3-query-20261116`。对应工作区位于 `~/.cache/asteria-workspaces/`，去掉日期后缀；每轮都有 registration、输入/源码/基线哈希、原始过程日志及独立检查。四轮均已追加 `final-result.json`，人工核对工具输入和实际差异并绑定原始证据 SHA；没有覆盖原 `pre-review-result.json` 或自动审计。四轮正式 Review/Accept 均 **NOT RUN**。

## 工程验证与后续

`553d5f7`：Windows 完整 1925 passed / 5 skipped / 42 deselected（517.80 秒）；相关 Windows/WSL 各 48 项、Ruff、mypy ratchet 和五离线基准通过。

`f3278a1`：Windows 完整 1927 passed / 5 skipped / 42 deselected（495.27 秒）；相关 Windows/WSL 各 58 项、Ruff 全仓、mypy ratchet 和五离线基准通过。

`c751865` runtime / `2313ff7` 测试：Windows 最终完整 **1941 passed / 5 skipped / 42 deselected**（496.28 秒），相关 Windows/WSL 各86项、追加受保护检查18项均通过；Ruff全仓、mypy ratchet（60已知/18已不再报告、未改基线）及五离线基准过。首轮全回归4个旧fixture将模型建议冒充用户必需，已改为原始用户输入明确该检查，原保护断言保留；旧失败日志留存。

GitHub API 实查 Verify workflow 的状态为 **disabled_manually**，已核对的四个提交均没有 Verify run 或 check-run；因此远端验证 **NOT RUN**，不借用旧 `9a0cb3e` 的绿色 CI。本轮没有调整工作流开关或配置密钥。

下一步保留 ACTIVE_SLICE=S131：用 D 的只读副本核实现有 Review 能否识别真实格式缺陷，再决定是否修共享验收覆盖的责任链；不预设一定缺功能、不向 runtime 加 RST 专用补丁。后续新任务用冻结 v4，不再同题刷绿。只有完整独立验收合格才正式 Review/Accept；shell 外搬移仍单列，不放宽破坏性 shell 权限，不外推小时级自主能力。
