# S77 · 全系统商业化就绪审计签字报告（2026-07-04）

- **方法**：多代理审计 workflow，15 个子系统逐个「设计 vs 真实现」映射，每条「已实现」声明交对抗式验证器复核（真 / 部分 / 桩·超卖 / 缺失），再三视角市场打分（怀疑型投资人 / 竞品 PM / 务实工程）→ 汇总 → 批判官修正。36 代理 · 2.77M token · 734 工具调用 · read-only（未改任何代码）。
- **一句话结论**：工程诚实度罕见、架构自洽的**晚期 alpha 本地优先 Agent harness**；实现广度≈**71%**，但权重压在「管道」而非「大脑」。市场化裸分 **37/100**，按其真实利基（单人本地/自托管/合规审计）调后 **43–45**。**今天不可商业推广，也非「作为产品」可融资——只作「团队 + 论点」早期赌注可融。** 差距是**能力差距**（沙箱、自主闭环），非打磨差距。

---

## 1. 实现程度盘点（15 子系统 · 已对抗式验证）

规律：**外壳/管道层扎实，大脑/承诺层名不副实。**

| 子系统 | 完成度 | 判定 | 真相（验证后） |
|---|---:|---|---|
| Studio 后端 server.mjs | 87% | 真 | 真起 Python CLI、流式读盘上真证据、无 fixture 回放；缺陷是 1.2s 全文件轮询、mtime 窗口可串联并发 run、正则脱敏 |
| CLI 命令路由 | 85% | 真 | ~50 子命令真派发真逻辑；help 仅露 ~14 个，maintainer/user 分隔仅展示层无访问控制，2 处诚实占位 |
| 文档/上手/打包 | 83% | 部分 | init/doctor/installer 真通、纯 stdlib 装得起；**无 LICENSE、pyproject 无 license 字段、wheel 落后一版、package-check 不构建** |
| 持久化/Schema 校验 | 82% | 真 | 原子 JSON/JSONL + 写时 fail-closed 校验真接生产；校验器手搓（忽略 minimum/pattern/$ref），无 fsync |
| 工具执行层 | 80% | 真 | 文件/shell/搜索/patch/预算/registry 真 FS 副作用 + 改前备份 + PathGuard；**shell 非沙箱 denylist、apply_patch 不能建/删文件、只读工具无预算** |
| Studio 前端 React | 80% | 真 | 全库最诚实块：无桩、真后端接线、诚实 run-state、SSE+轮询兜底、实时预览、逐轮 Keep/Revert、Ctrl+K、主题 |
| 上下文压缩/成本控制 | 78% | 部分 | 预算计量·0.75 自动压缩·0.90 硬停 DecisionPoint 真接活 provider；**"压缩"只写快照从不缩活提示、repair 账本故意未接、loop-guard 从不真停、token=chars/4+硬编码 200k** |
| Skills 执行 | 72% | 部分 | 指令注入管道（发现→gate→载入 SKILL.md 全文→证据）真、非桩；**但名不副实：无 skill 执行代码、仅自带 1 个 skill、参数契约摆设、无真 provider 测试证明模型遵循** |
| MCP 集成 | 71% | 部分 | 真 stdio JSON-RPC 客户端接了模型 + 真 gate/预算/证据；**仅 stdio（无 HTTP/SSE）、零默认 server、无 add-server UX、开箱休眠、默认空 allowlist 宽松、真传输测试被 env-gate 出 CI** |
| 规划/目标规格 | 70% | 部分 | GoalSpec 真 schema 校验 LLM 调用、plan 质量 gate 真拦真抛 DecisionPoint；**但分解与"质量分"是正则/关键词硬编码启发式 + 对 benchmark 名过拟合，是结构 lint 非推理；mid-run replan 是 resume 边界推荐非闭环** |
| Agent 循环内核 | 67% | 部分 | 每任务 Execute→Verify 内环真·模型驱动·schema 门控·过完成契约+合并 gate 才算 done；**但外层 Goal→Plan→repair→resume 停在 resume 边界交还人类——repair/replan 是"拦截并推荐一条命令"标记，loop-guard 观察式，`AgentLoopRunner` 是测试壳；非平凡目标的无人值守完成未被证明** |
| 多 provider 抽象 | 66% | 部分 | 真 HTTP OpenAI 兼容 + MiniMax + 本地 · 真 SSE · 重试退避 · 强→中降级；**无 Anthropic/原生 OpenAI/Gemini、真后端偏中国区、零配置默认廉价档是返回罐头输出的假货且能骗过 model-check** |
| 安全/安全策略 | 66% | 部分 | 保护路径/工作区边界/权限分级/DecisionPoint 真、denylist 有对抗测试；**但明确是静态字符串扫描无 OS 沙箱：`shell=True` 继承全部父环境、allow_shell 默认开、`python -c urllib` 一行绕全部出网/破坏扫描、beta_safe（唯一真遏制）opt-in 且默认关** |
| 验证/校验/修复环 | 64% | 部分 | verify→契约→合并 gate→晋升→review→accept 真跑子进程真门控真证据；**但吹的 S69 对抗验证器源码不存在（仅过时 .pyc）、DebugAgent 占位、repair 预算未接、review 分是按状态分桶常量、accept 有 --skip-review 后门** |
| 评估/gate/验收/真模型 | 55% | 部分 | 冒烟/矩阵/gate/验收/晋升管道真实现真做工件校验；**但招牌 MVP"≥0.8"量 UX 协议结构非代码正确性、唯一自动断言跑静态 fixture 零模型调用、唯一真 provider 签字放行的是卡 'blocked'、31MB 的 run、release gate 排除真 provider 测试** |

**总实现度 ≈ 71%**，但分母是"子系统广度"；决定商业价值的两项（**自主闭环** 与 **真安全边界**）落在 64–67% 与"占位/降级"。

---

## 2. 市场化打分（三视角面板 → 汇总）

面板裸分区间 **31 / 38 / 44**；汇总 **37/100**。各维度（满分 10）：

| 维度 | 分 | 要点 |
|---|---:|---|
| Studio/UX 成熟度 | 6.5 | 最强面：真起运行时+流真证据的诚实 Web 面；但是"仪表盘"非编辑器（无 LSP/debugger），仍单人本地 |
| 文档/工程纪律 | 6.5 | **最可融资属性**：单一真源计划、ADR、逐切片 brief、triage lock、会揭自己短的签字自审 |
| 可靠性/验证诚实度 | 5.5 | 两面：诚实到自曝其短（信任资产），但验证实质薄——招牌指标量结构不量正确性、S69 是空气 |
| 核心 Agent 质量（自主长任务） | 4.5 | 产品定义级承诺只交付一半：repair/replan 拦截+推荐命令不自恢复；唯一真 run 卡 'blocked' |
| 多 provider 灵活性 | 4 | "多 provider"言过其实：无 Anthropic/原生 OpenAI、偏中国区、默认档假离线 |
| 上手/打包/法务 | 4 | 机制在，但无 LICENSE、wheel 落后、无法确认已发布 Release——今天不可发货 |
| 差异化/护城河 | 4 | 论点自洽（本地审计链 + candidate/合并 gate + 可续），但每柱只交付一部分，无自有模型/数据飞轮/网络效应 |
| 工具/MCP/Skill 生态 | 3.5 | 管道真、生态休眠：零默认 MCP、1 个不执行代码的 skill、apply_patch 不能建删 |
| 安全/沙箱 | 3 | 项目自认 shell 是"减速带非边界"；对多租户/不可信输入是否决级 |

**批判官修正**：37 是拿它跟**通用付费编码 Agent 市场**（硬刚 Claude Code/Cursor/Devin）比出来的；而定位文正确地把它收窄到「单人/本地/自托管/合规」利基。按那个利基评，Security 3→4、Multi-provider 4→5、Differentiation 4→5（在位者的云/数据商业模式**天然不愿**做本地优先/无遥测——对该利基是软护城河；candidate/合并 gate/worktree 管道验证为真且强过在位者）。**「无一方前沿模型」从 P0 降 P1**（OpenAI 兼容口已通，真缺陷是假默认档）。**调整后 ≈ 43–45/100**：弱但差异化、团队信号强、P0 大多可修（唯沙箱对其真实利基是真难）的晚期 alpha 利基赌注。

**竞品定位**：vs Claude Code/Codex——人家用一方前沿模型闭合 edit→test→repair 且发货隔离，Asteria 外环遇 block 交还人类且无 Anthropic/OpenAI provider；vs Cursor——IDE UX/生态/模型接入完败，仅审计/合并 gate 框架有边；vs Devin——人家真云 VM 自主会话，Asteria 远程后台是明写桩且无沙箱；vs OpenCode——最接近同类，但对方 provider 广度与采用度更前。**现实卡位：隐私敏感/合规/气隙单人操作者的诚实可审计可自托管替代品——非付费开发者会舍免费在位者来选的通用编码 Agent。**

---

## 3. 距离商业推广的差距（排序阻断项）

**3 真 P0 + 2 P1** 挡在任何付费发布前：

- **[P0] 无 OS/进程沙箱**（allow_shell 默认开、继承全环境、解释器一行绕扫描）。任何付费/共享/不可信输入（prompt 注入）场景有项目自认"静态无法遏制"的任意代码/密钥外泄/删除通路。**~6-12 周**。*对"单人本地"利基与在位者平齐，可先不做发社区版。*
- **[P0] 无 LICENSE 文件/元数据**。无 license 不能合法分发/售卖/自托管。**<1 天**，绝对硬门。
- **[P0→降 P1] 默认档静默返回假输出 + 无一方前沿 provider**。零配置用户静默拿伪造输出。真难点只"假默认档改 fail-loud"（小时级）+ 补原生 Anthropic/OpenAI（~2-4 周，因 OpenAI 兼容口已通）。
- **[P1] 自主 repair/replan/resume 环未闭合**——即价值主张本身。**~4-8 周**（强制每任务预算下自动调 Debug/Replan、接 repair 账本、让 loop-guard 真停、真 provider 真 benchmark 证明）。**撞冻结，须先 DecisionPoint 决定是否解锁。**
- **[P1] 质量 gate 量 UX 结构非代码正确性**，唯一自动断言跑静态 fixture，release gate 排除真 provider。**~3-6 周**。
- **[P1] S69 对抗验证器源码不存在**（仅过时 .pyc）+ DebugAgent 占位。**~3-6 周**（实现，或删声明改文档）。
- **[P2] 生态休眠 + 发布卫生**（零默认 MCP、S69 空气、wheel 落后、docs 引用不存在的子系统）。

---

## 4. 战略盲点（批判官补 · 评估本身漏掉的商业化问题）

比技术阻断项更致命，动摇"能否作为付费产品"：

1. **商业模式未定 ≠ 加个 LICENSE**。本地优先/自托管/单人/provider 无关——几乎定义开源·开放核心，与**免费的 OpenCode/Aider 同轴**。选 license（宽松 vs copyleft vs BSL）就是选商业模式。
2. **中国 provider 栈 vs 西方合规买家的 GTM 矛盾**：glm/minimax 默认栈对西方合规买家是硬阻断；而这套栈天然适配中国/APAC。张力未分析。
3. **单一维护者 / bus-factor**：git 单作者、中文为主文档。卖点是"信我的可审计证据链"的产品，集中度风险 + 无安全响应保证，是企业买家一级顾虑。
4. **"可审计"对合规买家通常=防篡改**（密码学链式）。`.asteria/` 仅追加 JSONL 无完整性保护——护城河论点自身的洞。
5. **付费意愿未分析**：相关问题不是"凭啥不用 Claude Code"，而是"合规/气隙买家凭啥为可审计自托管 harness 付费，当 Aider/OpenCode 免费且可自托管"——付费点是合规/SLA/赔偿担保，均未定价。
6. **市场窗口**：编码 Agent 空间正快速向几家前沿实验室背书产品收敛；4-7 月估算未问"独立 harness 窗口是否正在关闭"——任何出资人的中心择时问题。

---

## 5. 现实路径（两档）

- **~6-8 周 → 诚实自托管社区 alpha**（免费/社区档，非付费）：LICENSE + 默认档改 fail-loud + 真·版本对齐已发布 wheel + 对 beta_safe 锁定态红队。
- **~4-7 月（2-3 名资深工程师）→ 安全可辩护的利基付费 Beta**：~1 人季度沙箱 + ~1 人季度闭合自主 repair/replan 环及真正确性评估 gate（可部分并行），外加原生前沿 provider、验证器/修复执行器、MCP/skill 生态、打包/法务并行，再红队 + 真 Beta。

**前提**：诚实团队延续；不追被冻结的北极星/swarm/12-Agent；拿到并接一方前沿 provider；不放弃本地优先；补英文上手。**与在位者通用自主编码正面平齐是更大的多季度工程，不建议近期目标——护城河只赢在本地优先/可审计/自托管/合规 wedge。**

---

## 6. 针对性 R&D 重排（待用户拍板的 DecisionPoint）

近期第一批可落地（小时~天级，无战略依赖，建议先做）：
1. 加 LICENSE 文件 + pyproject `[project.license]` 元数据（先决：选 license → 见战略分叉 A）。
2. 假默认档改 fail-loud（静默罐头输出 → 显式报错/拒绝）。
3. 版本/wheel/ACTIVE_SLICE 对齐 + package-check 真构建 + docs 去掉不存在的 S69 引用。

需先决策再动的战略分叉（**勿独断**）：A 商业模式/OSS 与 license 选型；B 目标市场（中国/APAC vs 西方合规）与 provider 区域；C "可审计"是否上防篡改（密码学链式证据）；D 是否解锁 DO_NOT_TOUCH 以闭合自主 repair/replan 环。

> 冻结不变：新编排 Wave、parallel_writes 全局默认、无真实 friction 证据的 Studio 新功能；北极星/swarm/12-Agent 继续冻结。

---

## 7. 定位澄清（2026-07-04 用户拍板）—— 重要，覆盖上文「商用就绪」框架

本报告 §1–§6 以「面向市场的付费编码 Agent」为基准打分（故 market score 37 / 利基 43-45）。用户澄清后，**该框架不是本项目的操作目标**：

- **本质 = 团队内部 AI 编程发动机 / 国产化基础设施**：促进 AI 飞轮迭代、服务后续各类软件解决方案、积累自有智能体经验、迎接未来风口。**不直接与 Codex/Cursor 等竞品对打。** 坚持自研的理由:国产化路线 + 行业突围需自有思路与实操经验。
- **目标市场 = 中国/APAC**，现有栈（glm/minimax）已适配；**不重接 Anthropic/OpenAI**（国产化）。
- **`LICENSE` = 内测期专有/内部使用约束**（避免代码放开、技术外泄），非 OSS、非商业 license 选型。

**据此重映射优先级（取代「商用就绪」阻断项）**：

| 原审计项 | 重映射后 |
|---|---|
| P0 无 OS 沙箱 | **降为加固项**：内部可信团队/单人本地与在位者（均不沙箱本地 shell）平齐;仅修 `beta_safe` 默认关的 footgun |
| P0 无一方前沿 provider | **非 blocker**：国产化即用 glm/minimax;真缺陷仅「假默认档静默假输出」 |
| P0 无 LICENSE | **已落地**：专有 LICENSE + pyproject 元数据 |
| P1 自主 repair/replan/resume 环未闭合 | **升为真正的内部第一优先级**（= 飞轮 / 经验积累核心;撞冻结须 DecisionPoint 解锁） |
| P1 质量 gate 量 UX 结构非正确性 | **保留高优**（飞轮可信度需真代码正确性 eval） |
| P2 生态休眠（MCP/skill） | **保留中优**（引擎干真活需工具生态） |
| P1/⑥ S69 空气 + 文档超卖 | 诚实化;S69 已如实标注源码缺席 |

**无争议第一批落地状态（2026-07-04）**：① 专有 `LICENSE` + pyproject `[project.license]` ✓;② wheel 版本对齐 0.2.0a2 ✓;③ docs 如实标注 S69 缺席 ✓。**「假默认档 fail-loud」经核实降为定向项、不在本批**：`factory.py` 真实零配置默认其实是 minimax（真的）,混用已有 `_warn_if_tier_silently_offline` 告警（既有 D-3 决策）,3 个测试耦合该行为——硬 fail 会砸离线测试基础并反转已录决策,留作后续定向诚实化（升告警可见度 + 校正 `default_routes` 显示表）。

**结论**：作为内部基础设施,操作目标 = 可靠性 + 智能体经验积累 + 国产化,而非市场竞争;真正值得投入的是**闭合自主环 + 真正确性 eval + 工具生态 + 诚实化**,沙箱与西方 provider 不再是近期阻断项。
