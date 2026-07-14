# ADR-0028 · release gate 独立重跑 = 信任但核验 acceptance 记录的绿

- 状态：Proposed（2026-07-14）——**设计立场 Proposed，代码已落地：acceptance 生产 + gate 只读消费，默认开（best-effort，缺信号自动退回只读）。**
- 关联：[[0018]] gate 量真代码正确性（本 ADR 深化其信号源）· [[0016]] 认知归模型/边界归状态 · 记忆 `model-games-tests-write-scope-gap`（作弊/说谎的另一面）· `commercial-readiness-audit`（P1⑤ 源）
- 授权：用户 2026-07-14 「P1⑤ release gate 自动重跑，展开讨论」→ 选定 **Option A + flaky 重试一次仍 fail 才硬 block**

## 背景

S77 审计 P1⑤：质量 gate 打的是 UX 协议结构分而非代码正确性。ADR-0018 已让 gate 用 acceptance 跑的真校验证据打分（`_acceptance_correctness`），堵了一半——**但它调的是 `CorrectnessEvalCommand.score_signal`（只读），信 acceptance 记录的退出码**。`correctness_eval` 里早有更强的 `rerun=True` 独立信号（把每条记录过的校验命令在当前 workspace 重新真跑一遍、检测 DIVERGENCE = 「记录 PASS、重跑却 FAIL」），但它只存在于手敲的 `asteria correctness-eval --rerun` CLI，**release 路径永不自动触发**。一句话:gate 信任但从不核验。

## 关键边界:重跑能抓什么、不能抓什么(必须诚实标注)

| 情形 | 独立重跑 |
|---|---|
| 工件过时/坏了/flaky（记录 PASS，现在 FAIL） | ✅ 抓（DIVERGENCE） |
| 伪造退出码（没真跑却记 PASS） | ✅ 抓 |
| 模型把被测文件放进 write_scope、删断言把测试改弱 | ❌ **抓不到**——弱化后的测试重跑照样过 |

所以本 ADR 是**反过时/反 flaky/反伪造**信号,**不是**完整反作弊。作弊那条（弱化测试本身）属另一把刀（禁止把已存在测试放进 write_scope,记忆 `model-games-tests-write-scope-gap`,未定,有 tradeoff）。两件事别混。

## 决策(Option A:acceptance 生产 · gate 只读消费)

- **acceptance 侧生产**:`AcceptanceCommand.run()` 在建报告后,对每个 scenario 调 `CorrectnessEvalCommand(workspace, run_id, rerun=True).persist_independent(run_dir)`——重跑该 scenario 记录的校验命令、把 `rerun_eval` + `overall` 独立信号**合并进它自己的 `correctness_eval.json`**。best-effort:任何重跑问题都不让 acceptance 失败(gate 自动退回只读)。
- **gate 侧消费**:`GateStatusCommand._acceptance_correctness` 改 `grader.independent_signal(run_dir) or grader.score_signal(run_dir)`——**优先读持久化的独立信号,没有才退回只读**。gate 仍**只读 `correctness_eval.json`、re-executes NOTHING**;重跑成本落在本就在执行的 acceptance。DIVERGENCE → 独立信号 status 非 pass → 复用既有 `acceptance_correctness_failed` stage → gate blocked。
- **flaky 护栏**:`_rerun_signal` 单条命令重跑失败**重试一次**(抽出 `_run_verification_once`);仅两次都 fail 才判 DIVERGENCE 并硬 block。飞轮可信度优先于偶发误杀。

**为什么 A 不是 B(gate 自执行)**:B 把 gate 变成会真跑测试子进程的副作用执行器——更慢、flaky 一次掀翻 gate、对 DO_NOT_TOUCH gate 语义扰动更大、且打的是 gate 时的 workspace(可能已合法漂移)。A 让重跑发生在 acceptance 产出 run_dir 的紧邻窗口,天然避开漂移。

**合规清单(触此环的改动必须逐条过)**:
1. gate 只读持久化信号,自身不执行任何命令(`_acceptance_correctness` docstring 的 re-executes nothing 契约不破)。
2. 无独立信号时逐字节退回今日只读行为(`independent_signal` 返 None → `or score_signal`)。
3. 重跑走 guarded `RunCommandTool`(ShellGuard + ADR-0020 env 消毒),从不裸 subprocess。
4. flaky 重试恰一次,不无限重试;两次都 fail 才算 divergence。
5. acceptance 生产 best-effort,异常吞掉不让 acceptance 失败(DO_NOT_TOUCH acceptance stack 的加法式扩展,非重构)。
6. 诚实标注范围:反过时/反伪造,**不吹反作弊**;弱化测试作弊另案。

## 后果

- 正面:release gate 从「信 acceptance 记录的绿」升为「信任但核验」——一个记录 PASS、实际已 stale/broken/伪造的 run 会被独立重跑抓成 DIVERGENCE 并 block,而不再放行。真代码正确性 gate 又深一层。
- 负面/成本:acceptance 每 scenario 多跑一遍其校验命令(用户选 A 时已接受此 acceptance-时成本);flaky 测试引入 gate 判决,由「重试一次」缓冲,但连续两次真 flaky 仍会误 block(可接受:飞轮可信度优先,且可后续加配额/隔离)。
- DO_NOT_TOUCH:gate_status / acceptance 均为加法式扩展(承 ADR-0018 在 gate 加 `_acceptance_correctness` 的先例),非重构;`correctness_eval` 非 DO_NOT_TOUCH。

## 回滚

无独立信号即天然退回只读(删/不生产 `rerun_eval` → gate 用 `score_signal`)。若开启后误 block 失控(flaky 泛滥),可在 acceptance 侧停 `_persist_independent_correctness` 调用一行,gate 自动全退回只读。
