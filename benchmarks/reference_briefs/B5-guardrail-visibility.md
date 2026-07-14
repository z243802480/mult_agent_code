# Slice B5 — 护栏 hook 干预可见(大重塑 Part B 前端拉齐 · 第二刀)

承 [B4](B4-expert-cluster-visibility.md)。B4 收官时列的四条"诚实推迟"里,这是第一条被接的。

## 用户看到的症状

**"模型莫名其妙又多跑了几轮。"**

根因:`pre_final` 续跑守门([execute_command.py](../../src/asteria_runtime/commands/execute_command.py)
`_methodology_stop_guardrail_decision`)在模型想收尾时做一次确定性证据检查——期望的交付物还没落盘
就 `continue_turn=True`,**把已经要关的循环拉回去**。它只写 `runtime_hooks.jsonl` 和 `events.jsonl`,
**不写 user_progress** → 主线程完全看不到,多出来的轮次没有任何解释。

## observed_pattern(行业已验证)

- **Claude Code 的 Stop hook**:钩子拦下"完成"时,会给用户一条**独立的系统消息**说明为什么没结束,
  而不是让对话静默地继续滚。拦截是边界行为,必须可见。
- **反面教材(本项目已确立的原则)**:`additional_context` 是**写给模型的提示词**
  ("Produce and verify them with tool calls before finishing.")——把它直接甩到主线程,就是把内部
  提示词当人话,正是 [[mainthread-scaffolding-cut]] 一直在砍的东西。

## asteria_mapping(怎么做)

**范围判断(两个 hook 只推一个)**:
- `pre_final` 守门 **真的改变了运行**(该收尾却不让收)→ **上主线程**。
- `turn_start` 方法论提醒只是给弱模型注入提示词 = **脚手架** → 留 Inspector,主线程不叙述循环如何
  自我提示。

### 后端
- `RuntimeHookDecision` 加结构化 `facts` 字段(`core/runtime_hooks.py`,**非 DO_NOT_TOUCH**)——守门
  把**事实**(缺哪些文件)交出来,人话由展示层拼;`merge()` 一并合并 facts。
- `_hook` 咽喉处:**仅当 `decision.continue_turn`** 落一张 `display_level="main"` 的卡,
  `data={held_open: true, hook_name, missing_artifacts, iteration}`。
  (Triage Lock 合规:`execute_command.py` 锁的原文是 "append user_progress only"。)

### 前端 —— 为什么必须新开一个 `guardrail` kind
两个"自然"的编码都不成立(实测):
- `transcript_kind="verification"` → 不在 `ConversationTurn.DETAIL_KINDS` 里,**被折叠**进"更多细节",
  用户还是看不见。
- `transcript_kind="repair"` + 非 failed 状态 → `narrative.ts` 明确把它当作"循环自言自语的记账"
  **过滤掉**;而标成 `failed` 是**撒谎**(运行没失败,只是被要求接着做)。

→ 新增一等 kind **`guardrail`**,按**稳定结构标记** `data.held_open` 识别(不靠标题文本),
进 `DETAIL_KINDS` + `LiveStream` 常驻卡,且 **`defaultOpen`**(要用户点一下才看得到的解释,等于没解释)。

### Inspector
`run-detail-reader` 补读 `runtime_hooks.jsonl`(此前 have-write-no-read),EvidenceExplorer 新增
「运行时 Hook」块——完整 hook 轨迹(含 turn_start)留在证据面。

## Definition of Done
- 真跑一个"模型不产出就宣称完成"的 run,主线程出现带 `held_open` 的卡并点名缺失文件,
  且 copy **不是**给模型看的英文提示词。
- vitest 锁死:`held_open` 卡不被脚手架过滤器吞掉、成为 `guardrail` 步骤、默认展开;
  普通 verification 行**不得**被误判成 guardrail。
- pytest 全绿;studio lint 0 error + build + 真 smoke。

## 实测发现(值得记)
守门对 **prose 占位符不生效是正确行为**:fixture 规划器给的 `expected_artifacts` 是
`"implementation artifact"`(不是路径),`_looks_like_path` 拒绝它——否则循环会永远等一个不可能
存在的文件。集成测试因此必须让规划器给出**真实路径**才能触发守门。
(这也暴露一个真实局限:**规划器不给具体路径时,守门就是哑的**。见"后续"。)

## 后续(承 B4 的推迟清单)
① 模型自组织 todo(`model_todos.json` 前端零引用)
② 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary` / 重复内容浪费)
③ 专家成本进汇总(child 不过 `worker_recorder`)
④ **守门哑区**:规划器产出 prose 占位符而非路径时,续跑守门无从检查(当前靠 benchmark 措辞规避)
