# S131 — 约束来源、缓存口径与新目标完整流程

> 后续状态见 [有界验证/授权闭环报告](S131-bounded-verification-loop-20261116.md)（1.2.232–1.2.233）。本报告保留前次来源/范围拒绝链快照；下一项已实际推进，不能把本报告的“待做”当当前状态。

2026-11-16。执行真源仍为总计划 §16.2，[brief](../../../benchmarks/reference_briefs/S131-content-preservation-contract.md)。本轮接续[Review实证](S131-review-artifact-proof-20261116.md)；旧四轮编码失败及其账本不改。

## 当前结论

来源和观察口径已核实并接线：原始请求是调用者输入，GoalSpec 扩展约束及 source 标签是模型解释；项目指导、执行权限与模型解释分别提供。生成缓存的扫描排除仅说明未观察，不能推出没有变化、获得授权或必然违规。显式用户/项目禁令继续有效。

完整流程确实运行了一个**新的按 ID 读取文档任务**，不是重跑旧 count/contains 题：冻结 facc208，187.43 秒、23 次 MiniMax-M2.7，原生 completed 并自动标为 ACCEPTED；独立验收却发现 3 个超范围 DB 文件，**整体验收拒绝**。原生自动收尾不等于正式模型 Review/Accept，不能把该状态写成用户目标已被独立验证。

据实补了两处工程保护：d4d4512 阻止已观察到显式边界外变化的运行自动验收；aaeada5 阻止模型 pass 豁免同类范围事实，保留模型原判并降为 partial/未知分。实际报告的生产函数回放及集成回归已证明保护，不把它冒充修复后的新模型整链成功。原始失败、DB 文件与自动收尾历史均保留；没有自动清理、审批越权或继续刷同题。随后在相同最终运行时代码上另做一次命名表任务：真实停在 DONE，标准 Review 明确范围失败并 partial/0.80，未 Accept，证明负向整链保护已生效；正向交付仍未验收。

## 核实和修复的事实

1. `GoalSpecAgent._normalize` 将 original_goal 覆盖为调用者原文，但 constraints、expanded_requirements、definition_of_done 及其中 source=user 都是模型提议。旧 verification_strategy_origin 只绑定方法来源，不能替其他字段认证。新增可选、runtime 覆盖的 proposal_origin，绑定最终持久化解释和原文摘要，区分 model_proposal/runtime_fallback；缺失或变更继续 unverified。它只证明生产者绑定，不是语义批准、权限授予或防磁盘篡改签名。旧目标不补签。
2. PlanCommand 已加载有界 root_guidance 和 project_commands，GoalSpec 的角色裁剪却丢掉二者。现补回已有事实，避免要求模型按未收到的项目规则溯源；不增加密钥或跨目录读取。提示约束模型不要把“不得新增用户交付文件”扩大成所有工具状态禁令，同时保留显式禁止生成物等要求。
3. 旧正控的缓存争议来自 find 的时间戳/存在列表及模型扩展约束，缺少登记的缓存内容前后比较。单次时间戳不是内容差异或权限裁决。workspace_snapshot 比较 mtime/size，并排除缓存、运行时及其他噪声目录；该排除表不是授权白名单。command_tools 现在公开实际共享扫描覆盖及局限，未知扫描仍为 unknown，不变成无副作用。
4. Review 在同一个来源绑定的产物快照中提供 review_basis：原始请求、模型解释来源状态、最多 16 KiB 的当前项目指导、扫描覆盖和已观察到的当前边界外历史路径。项目指导截断不能完整通过；“当前指导”不冒充历史执行时指导。指导模型区分旧任务与当前任务、现有产物与过程事实，不改目标/权限/必跑检查。
5. facc208 的新实跑证明 unscoped_changed_files 已记录三个 DB，但 auto-finalize 只检查命令绿和待 promotion，仍标 ACCEPTED。d4d4512 在唯一自动收尾位置复用 edit_boundary_allows 核对现有历史证据；只对显式 restricted 目标阻止自动验收，开放目标及正常范围内改动保持原行为。后续一轮绿色命令不会抹掉已知事件；不新造恢复状态机、不要求所有 run 强制调用模型 Review。
6. 同一共享函数给 Review 提供事实后，真实模型仍 pass/0.96。aaeada5 将已知显式边界问题纳入既有审批保护层，保存 model_overall_before_evidence_check，并降 partial/score=null。语义和修复方法仍归模型；这层不识别 DB/缓存扩展名、不更改授权、不自动删除。静态观察仍有盲区，不声称实现了 OS 写隔离。历史事件与新授权对不齐时，需显式澄清，不能默认洗白。

## 旧三控的新源码复核

冻结 facc208，仍用旧原样副本、原目标/指导，评估器不进模型提示；各一次标准 Review、各一次 MiniMax-M2.7：

| 对照 | 结果 | 秒 / 输入 / 输出 token |
| --- | --- | --- |
| 短标题线负控 D | **pass/0.97，漏检** | 16.33 / 52458 / 2214 |
| 错章节/样式负控 C | partial/0.80，识别错章节 | 24.05 / 44496 / 1512 |
| D 仅补足一个点的产物正控 | pass/0.98，不再将旧缓存时间戳直接判违规 | 39.35 / 52452 / 1574 |

旧目标无全解释生产者记录，快照诚实标 unverified，未补签。三个副本项目文件、工具账本及原 C/D 全部哈希保持；新增模型记录、token、快照引用与预算精确对应。**不能说模型格式识别已经稳定，也不能借上一版 D 的检出给本版签字。** 正控这次通过仅是一条样本证据，不是统计因果结论。所有旧负控均不 Accept。

## 新任务的预登记与独立判据

目标是 docs/usage.rst 的 Using Document IDs 下新增 Document lookup example：MemoryStorage 中存入 Nora(score=5)、Wei(score=8)，读取 ID 2、展示 ID 999 缺失，并展示两份存量保持；只允许编辑该文件并保留所有旧行。固定完整项目命令、32 iterations、原预算、auto/no-research、900 秒外部保险。目标理解、规划、执行均正常调用模型，无人工中途反馈或修改产物。

fixture 在调用前从已接受 S124 代码复制，原源不改；移除旧运行状态和旧任务专用 AGENTS/TASK_CONTRACT/BATCH_CONTRACT，预先写入本次通用指导：当前请求定义任务范围，允许普通验证工具状态，但显式禁令优先，禁止新增用户交付物和越权清理。fixture、工作区、源码、指导、目标及评估器均预登记哈希。这是新任务的基线准备，不是运行后改规则。

冻结 lookup v1 的 8 个控制通过，合法批量 7 例/逐条插入换变量 8 例，缺例、错输出、错章节、短标题、旧行变化、漏缺失 ID 均拒绝；guarded 项目基线检查通过。离线控制构造器曾误替换包名，已在付费采样前修正，不记成模型失败。

真实产物用逐个 get 展示两份文档，是用户允许的替代；v1 只接受一次 list 输出，独立判据过严。保留原 v1/拒收，新增 v2 和逐个展示/缺一份/错输出控制，11 项通过；真实产物在 v2 可执行验证通过 **9 例**。v2 不覆盖原三 DB 范围失败，也不回填冻结 v1 结果。旧 query v4 及其 17 控制不改，不宣称它覆盖新任务。

## 新真实流程和后修复证明

新例先有 None 显示问题，模型自行修为 print；一次过宽 doctest 执行了既有搬移示例，真实创建 db.json、db1.json、db2.json。后续检查通过，任务 contract_check.ok=true，同时 unscoped_changed_files 保留这三条。只有 docs/usage.rst 有原文整行插入，旧行未改；完整项目测试 271 passed/1 skipped。新目标 proposal_origin 真实有效、content_preservation 已提出，0 次方法修订调用。

23 个实际 MiniMax-M2.7 完成记录，690964 输入/17736 输出 token；41 本地工具调用/41 唯一关联观察、41 收费/30 单位，0 skill/MCP。调用、观察、预算和 token 均对账；原基线/fixture/runtime 哈希保持。原始 run 正式模型 Review/显式 Accept **NOT RUN**，自动 ACCEPTED 的不充分记录不改写。

后修复 d4d4512 在独立完整副本将阶段预置 DONE，仅回放生产 auto-finalize：识别三条实际边界外路径，skipped、0 新模型调用，原 run 字节不改。这是反事实工程证明，不是新目标重新实跑。

随后对该失败副本进行一次标准真实 Review，37.29 秒、1 MiniMax，41264 输入/3285 输出 token；快照已明确三 DB，仍 pass/0.96，**真实范围漏检保留**。副本未 Accept，原项目/工具账本及原运行全哈希保持。

aaeada5 对该真实报告/绑定快照直接调用生产 constrain_review_approval，结果 partial/null，原 pass 和原报告 SHA 保持；0 新付费调用、0 新模型采样。集成回归还用实际 shell 创建边界外文件，验证命令绿仍不自动验收、后续绿记录不冲销事件、模型 pass 被保留并降级，范围内/开放目标仍自动收尾。截至该反事实回放，修复后新模型整链尚未运行；后续另有命名表真实拒绝链实证，见下节，仍没有正向 Accept 成功。

## 最终运行时的新目标：真实拒绝链

完成 aaeada5 全回归后，新增冻结命名表题，源码登记 32cdd17（仅 benchmark/brief 变化，src/schemas 与 aaeada5 完全相同）。同样预登记输入、项目基线、通用指导与 900 秒/32 iterations；9 个独立控制通过，合法逐条/批量各 9 例，缺例、错输出、表混杂、错章节、短线、旧行变化及漏一表展示均拒绝。原 lookup 失败不重跑，没有中途反馈或改工作区。

实际 353.08 秒原生 completed。产物在 Tables 下正确展示 active/archive 各自内容，独立 **9/9 示例**、完整项目 **271 passed/1 skipped**，旧行/实现/配置保持；但一次过宽 doctest 真实创建 db.json，未恢复，范围拒收。当前保护真实生效：native workflow=ready_for_review、phase=DONE，accept 步骤 skipped 并列出 db.json，没有自动 ACCEPTED。

随后在同一 run 执行一次标准 Review，46.33 秒、1 次 MiniMax-M2.7、85913 输入/4880 输出 token。实际模型判定 partial/0.80，明确指出 db.json 是验证生成的边界外文件；没有用工程覆盖伪装成模型检出，model_overall_before_guard 为空。原生终态、原模型/工具账本前缀、当前项目文件保持，正常追加 Review 元数据和一条模型记录；新鲜快照和请求引用一致。独立范围失败，**显式 Accept 未运行**，不删除数据，也不再发起其他目标求绿。

累计 24 个实际 MiniMax-M2.7 记录，764288 输入/30713 输出 token；34 本地工具调用/34 唯一关联观察、34 收费/29 单位，预算和 token 精确对账。新 proposal_origin 有效、content_preservation 真实提出。修复后的真实负向 Goal→Execute→Review→拒绝验收链已验证，**正向 Goal→Review→Accept 成功仍未验收**。这不是成功交付、统计稳定性或小时级自主证明。

## 证据位置

WSL `~/.cache/asteria-evaluations/`：

- `s131-review-scope-20261116`：旧三控登记/结果/快照和 source-scope-audit。
- `s131-source-scope-lookup-20261116`：新任务 registration、冻结输入/源码/基线、原始日志、final-result、identity-origin-accounting-audit。
- `s131-lookup-v2-20261116`：新判据及 11 控制/实际产物反事实，不改原 v1。
- `s131-scope-gate-proof-20261116`：0 模型自动收尾回放、一次真实 Review 原报告、绑定快照及 review-boundary-counterfactual。
- `s131-source-scope-tables-20261116`：最终运行时新命名表题、9 控制、原生 DONE、独立检查、negative-review 和 final-lifecycle-audit。

原 run 与副本的 run_id 相同，必须结合工作区识别。失败样本不清理，未跟踪验证目录不入 Git；只提交源码、测试、公开 benchmark 资产与说明。没有读取/推送凭证、开启远端 keyed 工作流或部署。

## 工程验证和下一步

facc208 完整 Windows **1973 passed/5 skipped/42 deselected，477.69 秒**；相关 Windows/WSL 各 72 项通过。后续运行相关两端各 39 项；最终 Review/范围集成两端各 21 项通过。Ruff 全仓、mypy ratchet 无新增（60 已知/18 已不再报告，未更新基线）、五离线基准过。

最终源码 aaeada5 完整 Windows **1976 passed/5 skipped/42 deselected（460.38 秒）**。d4d4512 的中间全套因实际新增 Review 边界修复而中止，不称通过；日志保留。公开 GitHub API 实查最终源码 Verify 仍 disabled_manually，0 run/check-run，远端 **NOT RUN**。

下一优先仍是 S131 的真实验证副作用闭环：两种新目标均因过宽检查留下数据文件，下一刀先调研并复用已有模型指导、工具事实和权限请求，促使验证前核对范围、发生实际事件后明确请求授权/恢复，不把“命令后来变绿”当完成。暂不再无修改付费换题采样；修复有证据后再登记独立正向整链。细小格式识别也未稳定，需研究适用的可执行检查/证据，而不是 RST/provider 补丁。新编排、强沙箱和额外 Studio 功能继续冻结。
