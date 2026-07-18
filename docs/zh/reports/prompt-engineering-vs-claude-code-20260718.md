# 内置提示词对标 Claude Code — 评估与「驾驭模型」学习

日期：2026-07-18　范围：`src/asteria_runtime/` 全部 model-facing 提示词　方法：逐条回代码核实（非印象）

> 这是一份**快照评估**，引用前对照 changelog。所有「我们怎么做」的断言都标了代码位置，可复核。

---

## 0. 一句话结论（headline）

**我们其实已经有一套 Claude-Code 对齐的、密集的 master 系统提示（`AgentHarness.prompt_envelope`，含 scope_fidelity / tool_policy / execution_discipline / failure_repair / safety_envelope / user_communication / 注入 AGENTS.md 的 project_guidance 等 13 段），但它被 `persist_prompt_envelope` 落盘成 evidence 工件 + 按 hash 记进 model_call 日志，`context_prompt_view` 还[显式剔除它的 payload](../../src/asteria_runtime/core/context_prompt_view.py)——立真身执行循环真正喂给 doer 的 system prompt 是 [`_model_driven_prompts`](../../src/asteria_runtime/commands/execute_command.py) 里那段约 6 行的薄 CoderAgent 文本。好的提示工程存在，但没到达干活的模型。**

换句话说：我们和 Claude Code 的差距**不主要是「没写好规则」，而是「写好的规则没接到热路径」+「把该常开的方法论设成了 opt-in」**。这对强模型（Claude）无所谓，对我们目标栈的 glm/minimax 弱模型是**驾驭不足**——dogfood 那次「46 次工具调用零写入」就是活体证据（模型从没主动调 `investigate`/`verify` 技能，只在薄提示下空转）。

---

## 1. 已核实的提示词版图

| 提示 | 位置 | 是否喂给 doer 热路径 |
|---|---|---|
| **薄 CoderAgent 提示**（doer 实际 system prompt） | `execute_command.py` `_model_driven_prompts` | ✅ 是（唯一） |
| **可选方法论指导** | `execute_command.py` `_methodology_guidance` | ✅ 是（附在 system prompt 后） |
| **JSON turn 契约** | `model_driven_turn.py` `_JSON_TURN_CONTRACT` | ✅ 是 |
| **过早收尾轻推** | `model_driven_turn.py` `_grounding_nudge` | ✅ 是（仅触发时） |
| **富 master envelope**（13 段·CC 对齐） | `agent_harness.py` `prompt_envelope:752-951` | ❌ **否**——只落盘 evidence + 记 hash，`context_prompt_view` 剔除 payload |
| **项目指引 = AGENTS.md** | envelope `project_guidance` 段 | ❌ **否**（随 envelope 一起不到达·坐实 ADR-0024「AGENTS.md 待做」） |
| 6 个 bundled 技能（debug/investigate/minimal-change/plan/verify/retrospect） | `skills/bundled/*/SKILL.md` | ⚠️ **opt-in**——模型只看到一行 description，得自己调用才加载步骤 |
| 专家 persona（coder/diagnostic/reviewer/researcher） | `expert_registry.py:29-72` | ✅ 追加在子代理 system prompt 后 |
| goal_spec / review / brainstorm / research / chat / router / recap / 判官 | 各 agent 文件 | ✅ 各自 agent 用（非 doer 热路径） |

**注**：非 doer 的那些 agent 提示（goal_spec、review、chat、router、recap）质量其实不错——scope 保真、诚实化、语言镜像、「不虚构结果」都写到了。**问题集中在 doer 热路径这一条**，因为那是真正把活干出来的地方，却拿的是最薄的提示。

---

## 2. 逐维对比：Claude Code 怎么驾驭 vs 我们

Claude Code 驾驭模型的经验，核心是一条**始终在线、密集、带理由的行为规则系统提示**。逐维对照我们的 doer 热路径：

| 维度 | Claude Code 的做法 | 我们 doer 热路径的现状 | 差距 |
|---|---|---|---|
| **约定优先 / 模仿现有** | 强制「先读现有代码、对齐风格、**确认库已被使用再 import**、优先改而非建」——这是 CC 避免幻觉依赖、产出可合并代码的**头号规则** | 薄提示只有「smallest change / stay in write_scope」。「读现有代码、对齐风格」在 `minimal-change`/`investigate` 技能里，但**opt-in** | 🔴 高。正好也是 ADR-0024 doer 自觉差距的解药 |
| **动手前先理解** | explore-before-edit 几乎是纪律 | `investigate` 技能有，但 opt-in，弱模型不会主动调 | 🔴 高（dogfood：模型在薄提示下瞎搜 46 次没落地） |
| **验证纪律** | 改完必跑 lint/typecheck/test；**别假设测试框架，先查** | 薄提示有「verify with run_command/run_tests before finish」+ 完成契约硬校验 | 🟡 中（有底线，但「别假设框架」等细节埋在 opt-in 技能） |
| **工具效率 / 批处理** | 显式「独立调用并行批处理」「用专用工具别用裸 bash」 | JSON 契约说「可一步多工具」，但无并行/专用工具偏好引导 | 🟡 中 |
| **反模式约束** | 「别加没要求的注释」「别乱建文件」「别 gold-plate」——密集且各带理由 | envelope 的 `scope_fidelity` 写了，但**不喂 doer**；薄提示只有「smallest change」 | 🟡 中（规则已存在，没接线） |
| **项目约定注入** | CLAUDE.md 始终在系统提示里 | AGENTS.md 经 envelope 注入，**不到达 doer** | 🔴 高（ADR-0024 已标） |
| **沟通/简洁** | 简洁、无 preamble/postamble、不复述 | `run_recap`/`user_communication`/一句话 narration 都好 | 🟢 低（这维我们不弱） |
| **结构通道** | 原生 tool_use | 被弱模型栈逼用 **JSON turn 契约**（glm/minimax 原生 tool_use 不可靠·`openai_compatible._parse_response`） | ⚪ 结构性差异·非提示问题 |

---

## 3. 核心学习（thesis）

**Claude Code 靠一段「始终在线、高密度、带理由」的规则系统提示驾驭模型。我们把等价内容拆散了**：
- 富规则（scope_fidelity / tool_policy / failure_repair …）在 `prompt_envelope` 里，但**只落盘不喂模型**；
- 好方法论（investigate / minimal-change / verify …）在 bundled 技能里，但**opt-in**，弱模型不会主动调；
- 结果：doer 拿一段约 6 行的薄提示上阵，还得**自己选择**去加载好方法论——一个弱模型（glm/minimax）在这种「自助」姿态下就会像 dogfood 那样空转。

**ADR-0016 的极简主义（认知归模型、方法论 OFFERED 不 FORCED）对强模型是对的，但对弱模型栈可能是欠驱动。** ADR-0016 自己留了口子：「弱模型脚手架由 eval 定，不由反射」——**dogfood 的零写入就是那个 eval 信号**。所以这不是要推翻 ADR-0016，而是它自己的判据触发了：证据表明该给弱模型加常开脚手架。

---

## 4. 按杠杆排序的建议（改前都需一次不可满足/读密集任务真栈复验，避免「反射式堆脚手架」）

1. **🔴 把「常开必备五条」接进 doer 热路径**（最高杠杆）：约定优先 / 动手前先读目标 / 改完先验证 / scope 保真 / 工具批处理。两条路线——(a) 直接把 envelope 的相关段喂进 `_model_driven_prompts`（复用已有文字，别重写）；(b) 在薄提示里加这五条精炼规则。倾向 (a)+精简，因为 envelope 文字已在、且能顺带修复「envelope 建了不喂」的怪相。
2. **🔴 把 AGENTS.md/项目指引喂给 doer**（ADR-0024 已标的已知缺口）：doer 现在完全看不到项目约定。
3. **🟡 让关键方法论对弱模型「默认在场」而非纯 opt-in**：不必强制阶段，但可把 investigate/verify 的**精髓一行**常驻薄提示（「编辑前先 read 目标区、完成前先 run_tests」），技能仍按需加载完整步骤。
4. **🟡 加工具效率引导**：并行独立调用、优先专用工具（read_file/search_text）而非裸 shell。
5. **⚪ 评估在支持的 provider 上启用原生 tool_use**：结构性、独立一条线，非本轮。

**诚实边界**：以上是**评估结论 + 提案**，本报告**未改任何提示词**。每条落地都应先在一个读密集/不可满足任务上真栈复验有增益（ADR-0016 eval-not-reflex），再逐条提交——就像我们修 doer 失明/fuse/持久化那样一刀一验，不一次性大改 doer 提示。

---

## 5. 复核指针（reviewer 可据此打假）

- envelope 建了不喂：`execute_command.py:330,343`（`persist_prompt_envelope` + `context_ref()`）、`context_prompt_view.py`（`payload_omitted=True`）、`_model_driven_prompts` 的 system_prompt 自建。
- doer 薄提示全文：`_model_driven_prompts` system_prompt + `_methodology_guidance`。
- 技能 opt-in：`skill_adapter.py`（progressive disclosure，模型只见 description）。
- dogfood 证据：`docs/zh/研发总计划.md` changelog 1.2.124–1.2.125（doer 失明修复 + 真栈捶打）。
