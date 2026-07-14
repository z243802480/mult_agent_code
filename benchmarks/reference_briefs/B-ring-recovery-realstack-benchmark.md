# Brief · 自主环真栈 ring-recovery benchmark(S77 P1「真 benchmark 证明」)

- 日期：2026-07-14
- 关联：S77 审计 P1「自主 repair/replan/resume 环 + 真 provider 真 benchmark 证明」· [[flywheel-first-ignition-proven]](绿地 happy-path 首过)· [[ring-realstack-validation-A]](一次性 throwaway smoke·抓过收敛 bug)· ADR-0016(认知归模型)· ADR-0027(soft-fuse 续跑环)
- 授权：用户 2026-07-14「接自主环真 benchmark 证明」

## 问题(缺口)

自主环(auto_repair/auto_replan/auto_replan_goal)已闭合并在真 glm/minimax 栈**多次**验证会 fire-and-recover——但那些验证全是**一次性、手动、throwaway 的 `ring_val_*` workspace + 手敲 smoke**([[ring-realstack-validation-A]])。**没有可复跑、签入仓库、产持久工件的 ring-recovery benchmark**。审计 P1「真 provider 真 benchmark 证明」= 把 ad-hoc smoke 固化成确定性可重跑基准。

现有最接近的 `benchmarks/failing_tests_project`(`scripts/run_benchmarks.py`)有三个致命差:①**fake 栈**(FailingProject*Client 确定性桩,非真模型);②用**显式 `DebugCommand`** 驱动修复,不是让**环自 fire**;③断言落 `task_execution_evidence.jsonl`,不证真 provider。

## 与 flywheel 首过的关键区别(为何这不是重复)

[[flywheel-first-ignition-proven]] 证的是**绿地创建**(从零写 greet CLI·模型一遍写对·三环武装未触发)=happy-path。本 benchmark 证的是**诊断+修复一个客观损坏的基线**(buggy `add` 返回 `a-b`·1 failing test)——这是价值主张本身:引擎能不能在**无人干预**下把一个**已经红的**项目自主修绿。

## 架构校正:model-driven 世界里"repair 环 fire"长什么样

`budget.record_repair_attempt` **intentionally unwired**(`core/budget.py:185-193`)——ADR-0016 下**没有离散 repair-dispatch 计数器**(`budget.repair_attempts` 恒 0,别拿它断言)。"自主 repair 环"= 运行时在**无人门**下**允许模型在有界 loop 内继续跑**(`_loop_continuation_requested` `execute_command.py:554`),让模型自己「跑失败校验→见红→改→重跑→见绿→done」;循环由 `max_rounds` + 无进展检测兜底(主流做法:done=模型停手·扁平计数)。环的门控=`_auto_repair_enabled`/`_auto_replan_enabled`(`execute_command.py:432/450`·随 `permission_mode` 默认绑定·`autonomy_rings_default_on`)。

## 定义完成(DoD)= 证据契约

一个 ring-recovery run **PASS** 当且仅当(全部独立核验·不信 harness 自述):

1. **基线红**:seed 后、run 前,独立 `python -m pytest tests` **FAIL**(客观损坏)。
2. **终态绿**:自主 run 后,独立 `python -m pytest tests` **PASS**(引擎真修好了)。
3. **loop 内红转绿**:`tool_calls.jsonl` 里存在**失败的**校验命令(run_tests/run_command status≠success)**之后接**通过的校验命令——证明模型确实撞了失败又恢复(非侥幸一枪绿)。记录但不硬卡(模型可能读码推理后一次跑绿·基线红+终绿已是硬证)。
4. **环收尾**:`agent_loop_run_summary.json` `status=="completed"` 且 `exit_reason=="completed"`(非 blocked/repair_dispatch/max_rounds)。
5. **真 provider**:`model_calls.jsonl` 里执行 tier 的 `model_provider` ∈ {glm/zai/zhipu, minimax}(非 fake/offline)——否则 NO-REAL-PROVIDER;`--allow-fake` 时豁免(仅测 harness 管道)。
6. **无人门**:全程 reviewed_auto·环默认开·无 DecisionPoint/权限暂停打断(无显式 DebugCommand·无人敲 resume)。

**诚实三态**:PASS(全满足)/ NO-RECOVER(基线红但终仍红=环没修好·如实报告)/ NO-REAL-PROVIDER(跑了 fake)。绝不假成功。

## 实现(最省·复用已证骨架)

`scripts/ring_recovery_smoke.py`(自包含·抄 `concurrent_experts_smoke.py` 骨架):
- 隔离 workspace:`mkdtemp` → `InitCommand` → 改 `policies.json`:`agent_loop.model_driven_turn=True`、`permission_mode="reviewed_auto"`(**证默认绑定 arm 环·不显式设 auto_repair flag**)→ 拷 `benchmarks/failing_tests_project/fixtures/`(buggy_math.py + tests/test_buggy_math.py)。
- 基线红核验:run 前独立 pytest。
- plan 用 `SeedGoalClient`(fake 脚手架)+ 覆写 `task_plan.json` 塞单任务「修好 tests/ 使 pytest 通过」(write_scope=[buggy_math.py]·expected_artifacts=[buggy_math.py])。
- 真执行:`create_model_client(None, ...)` + `ExecuteCommand(ws, run_id, model_client, context_overrides={"execution_model_tier": tier})`——执行层 auto_repair 环在无人门下自主迭代。
- 断言:读 run_dir 工件核验证据契约 6 条 + 独立 pytest。产 `--summary-json`。
- `--tier {strong,medium}`(默认 strong=glm)· `--allow-fake`(管道自测·豁免真 provider 断言)· `--keep`。

**范围**:本切片证**执行层 auto_repair 环**(价值主张核心)。goal-level replan 环(run_command·已由 [[ring-realstack-validation-A]] 验并抓 bug)、soft-fuse 续跑环(ADR-0027 集成测)、auto-accept(单测)各自已有覆盖;全 RunCommand 端到端串联变体留后续。

## 验证本 benchmark 自身

- 断言逻辑抽成可单测的纯函数(`evaluate_ring_recovery(run_dir, baseline_red, final_green)` → verdict),喂合成 fixture 单测(确定性·无真模型):基线红+终绿+completed → PASS;终仍红 → NO-RECOVER;fake provider → NO-REAL-PROVIDER。
- `--allow-fake` 跑通证 harness 管道不炸。
- 真栈跑一次产绿证据(glm)= P1 持久证明落地。

## 真栈点火结果(2026-07-14 · glm-5)

**首跑即抓到真收敛 bug**:`--tier strong`(zai/glm-5)下,模型 tool 时序 = pytest(fail·基线红)→ write_file(overwrite 修 `add` 为 `a+b`)→ pytest(**pass**)——代码修对、独立 pytest 绿——**却** `status=blocked, exit_reason=tool_failed, viol=['verification did not pass']`。根因(`task_contract.py:293`):`verification_passed != verification_total` 把**修复场景必然的初始失败测试**(total=2/passed=1)计成永久失败 → 真修好的活被误判 blocked → **击穿 repair 环**。

**修**:`execute_command._latest_verification_per_command`——完成契约按**校验命令去重取最新结果**判定(同命令 red→green 算过;换命令蒙混则该命令最新仍红·保 ring_val_f 反作弊)。

**修后真栈复验 PASS**:`baseline_red=True · final_green=True · loop_status=completed · exit_reason=completed · red_then_green_in_loop=True · used_real_provider=[zai] · rounds=6`。即:损坏基线 → glm 无人门自主诊断+修复 → 独立 pytest 绿 → 契约判 done。**benchmark 兑现了价值:建证明工具→抓真 bug→修→闭环复验。**

复跑:`python scripts/ring_recovery_smoke.py --tier strong`(需 glm key);CI 无 key:`--allow-fake`(仅测管道)。

## 全 RunCommand 端到端串联(`--driver run` · 2026-07-14 · glm+minimax)

`--driver run` 驱动**整条自主环**:research(关)→plan(真模型)→execute(repair 环)→goal-replan 环→**auto-accept**。`permission_level="reviewed_auto"` 经 RunCommand **真实 arm 全部环的默认绑定**(execution 层 auto_repair/auto_replan + goal 层 auto_replan_goal/auto_continue/auto_accept)——**不设显式 flag**,证默认绑定本身。PASS 额外要求 `final_phase=="ACCEPTED"`(auto-accept 在正确性门下自动收尾)。

**又抓到一个同族隐患**:`_maybe_auto_finalize`(auto-accept)用 `CorrectnessEvalCommand.score_signal`(只读),而 `_signals` **也**按全部校验调用算 pass_rate——repair 若**先测(红)后修**则 rate=0.5→"partial"→**auto-accept 不 finalize→无监督修复永远不自动收尾**(与执行层 `verification did not pass` 同族·不同函数)。**修**:`_signals` 同样**按命令去重取最新**(与 `_latest_verification_per_command`/`_rerun_signal` 一致)。此修让 auto-accept 对"先测后修"路径也稳,不再靠模型碰巧"先修后测"。

**真栈复验 PASS**(两跑):`baseline_red · final_phase=ACCEPTED · loop completed · final_green · real_providers=[minimax, zai]`(全端到端两 tier 都真用上)。即:损坏基线 → glm+minimax 全自主 plan→修复→环→正确性门 auto-accept→ACCEPTED,**零人干预**。`--driver execute` 仍单证执行层 repair 环(确定性 seed)。
