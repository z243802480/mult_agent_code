# Slice — 正确性门自动收尾(set-and-forget #2 · 知情推翻 2026-07-02 DecisionPoint)

承低负担缺口地图 #2 + 用户 2026-07-13 **知情授权**推翻当年"run 停 ready_for_review·不 auto-accept"
的刻意 DecisionPoint。目标:干净验证过的 run 自己 finalize,砍掉每次 run 尾巴多余的 `asteria accept`。

## observed_pattern(行业已验证)
- **Claude Code / Codex 根本没有 "accept" 这一步**——改动直接落盘、跑完即完。所以"accept 收尾仪式"
  本身才是非主流;主流是 set-and-forget 直接完成。
- **但当年调研(§16 v1.2.15)的核心顾虑是"别把 review 硬编进 run 循环"**(CC 用 hook 不硬编),
  当年据此**弃 run-then-review 包装 + 缓做内联 review**,并把 run 设计成停在显式 review/accept。

## asteria_mapping(我们怎么做)
- **关键澄清**:当年顾虑=别硬编**模型 review**;本刀**不跑任何模型 review**——只按 run 期间**已经跑的**
  真测试退出码(ADR-0018·`CorrectnessEvalCommand.score_signal`)判定,故当年顾虑不被违反。真正被推翻的
  只是"auto-**accept**"那半条(用户知情后拍板)。
- 文件 `commands/run_command.py`(改 DO_NOT_TOUCH·解冻授权):新增 `_maybe_auto_finalize`(主完成路径
  写 final report 前调)+ `_auto_accept_enabled`(随权限档:auto/reviewed_auto→on·ask_everything→off·
  显式 `agent_loop.auto_accept` 覆盖)+ `_pending_candidate_promotions`。逻辑:run 干净 `completed` +
  `score_signal.status=="pass"` + 无 pending 风险 promotion → 翻 `current_phase=ACCEPTED`(bookkeeping)。
- **边界(留给人的真抉择点·非减配)**:blocked/paused 不 finalize;**未验证**(无可执行验证→正确性未证)
  不 finalize·留给人;验证失败不 finalize;pending 风险 promotion 留给人批。ask_everything 完整保留
  显式 run→review→accept。**不调 ReviewCommand**——run/review 分离 + "run 零 review 模型调用"不变量守住。

## 影响与验证
- 处理过程诚实(踩了两版):**第一版走完整 AcceptCommand(含 review)砸了 4 条 run 测 + 违反
  `does_not_invoke_review` 不变量→回退**;深查发现"run 停 ready_for_review·不 auto-accept"是命名测锁定的
  刻意 DecisionPoint→**回退并把证据+理由摆给用户知情决定**→用户拍板推翻→上正确性门版(不跑 review)。
- 爆炸半径:仅 `test_user_workflow_loop.py` 9 条(用 verified 完成 run 测 surfacing/routing/status/chat/
  session)+ 1 条 run 集成。处理:7 条 collateral pin `ask_everything`(保 pre-accept 稳定 fixture·主题
  mode 无关)+ 2 条 mode-命名不变量按新行为重写(auto→auto-finalize 且**证无 review 模型调用**;显式路径
  改测 ask_everything)。
- **新测**:`test_run_command_auto_finalizes_verified_run_under_reviewed_auto`(验证过→ACCEPTED·无
  eval_report/review_report·model_calls 无 review purpose)+ `test_run_command_does_not_auto_finalize_
  unverified_run`(无验证→不 finalize·implemented_needs_review)+ workflow 层 auto/ask_everything 双测。
- 全量 **1218 passed**(仅 6 条既有失败·无关)·ruff 净·mypy 零新增。

## do_not_copy(禁止照搬)
- 不把模型 review 硬编进 run 循环(守当年顾虑·CC 用 hook);正确性门只认真退出码。
- 不 finalize 未验证/失败/blocked/pending 风险 promotion 的 run(那些是留给人的真抉择点)。
- 不动 ask_everything 的显式 run→review→accept(完整保留)。

## 实现记录
- date: 2026-07-13
- notes: §16 v1.2.28 + 缺口地图 #2 勾掉 + 记忆 `low-burden-set-and-forget-ux`。知情推翻 v1.2.15 DecisionPoint。
