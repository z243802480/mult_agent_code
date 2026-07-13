# Slice B2 — 护栏诚实化 + 上下文压缩(立真身默认路径复验)

大重塑 Part B。开工前测绘结论:计划 Part B 的 B2 字面目标(删
`execution_action_preparer._ensure_planned_verification` 伪 DoD 注入 +
`context_slimming` 去硬编码 `classify_fast_path`)写于 RA7b 收官前,**已大部过时**。
按 CLAUDE.md「文档说谎改文档/代码不对改代码」诚实重定范围。

## observed_pattern(行业已验证)
- **Claude Code / codex-rs**:harness 不伪造验证步骤;模型自己决定验证(跑测试/命令),
  harness 只在**边界**上确定性否决"完成"(缺产物/缺验证证据 → 不算 done)。
- **渐进式披露**:验证提醒对弱模型加密度、对强模型减脚手架(density by tier),不每轮复读。
- **上下文压缩**:压缩触发应由客观信号(预算/上下文压力)驱动,而非硬编码任务类型猜测。

## asteria_mapping(我们怎么做 · 对齐当前真实代码)
- **①伪 DoD 注入 = 已删,无残留**。`execution_action_preparer` 整个模块(含
  `_ensure_planned_verification`)已在 RA7b task6a(`30259d6`)随 FSM 认知脚手架整体删除。
  模型自验证现由三处提示/边界共同保证,**无需再改代码**:
  - `core/model_driven_turn.py` JSON 契约(L49):"complete AND verified 才 done=true";
  - `commands/execute_command.py::_methodology_turn_start_decision`:对弱模型 iter1 注入
    "verify your work (run_tests / run_command) before finishing"(density by tier);
  - `commands/execute_command.py::_methodology_stop_guardrail_decision`(pre_final)+ RA7b-4
    正确性 gate(`task_contract.check_completion_contract`):产物/验证缺失 → `blocked`(边界否决)。
- **②去硬编码 classify_fast_path(执行路径)= 删死代码**。
  - `core/context_slimming.py::slim_execution_context` / `execution_context_policy` /
    `_execution_target_files` + 私有 helper(`_slim_top_level_lists`/`_slim_context_package`/
    `_slim_context_item`/`_slim_prompt_envelope`/`_capability_names`)是 FSM 执行循环遗孤——
    **全仓零调用者**(连 execute_command 历史上都从未按名引用),随 RA7b slice3f 删
    `for round_index` 循环后成死代码。删之即"去掉执行路径上的硬编码 classify_fast_path"。
  - **保留 `slim_review_context`**:它是活调用(review_command:234·仅真 provider 生产路径省
    token 时裁剪 review 证据),`classify_fast_path` 在此是**跨 plan/execute/review 单一真源**的
    风险/复杂度策略(§16 slice3a),驱动 review-tier 路由 + context_mode + 验证要求。单把它换
    context_pressure 会割裂单一真源、且无 friction 证据 → 是回归不是改进,**不改**。
  - **context_pressure 驱动的动态压缩 = 暂缓(honest defer)**:脊梁现于 load 时已由
    ContextLoader 有界投影(ADR-0024),无上下文溢出 friction 证据;新增动态 compaction 是
    「加功能」违反收敛纪律。待真实 friction 证据再做(记 ADR-0025 §deferred)。
- **③真栈复验**:真 glm(strong)+minimax 端到端复验立真身默认路径 happy-path(create+验证),
  + `@spine_default` 4 锁定测确认 RA7b-4 正确性 gate 仍守(验证失败/缺验证/越权写无工件/
  verification_calls 上报 → blocked)。删死代码与 gate/脊梁正交,不可能回归,复验坐实之。

## do_not_copy(禁止照搬)
- 不恢复任何 FSM 认知脚手架(execution_action / auto-inject verification / 状态机 repair 分支)。
- 不给 harness 加"替模型判断该不该验证/该压缩多少"的认知(ADR-0016:认知归模型,harness 只边界)。
- 不为「计划这么写」而改活的单一真源 classify_fast_path;不无 friction 证据加 compaction 功能。

## 实现记录
- date: 2026-07-13
- notes: 见下方 commit + 研发总计划 §16 回写 + ADR-0016/0022 对齐 + 已删除登记。
