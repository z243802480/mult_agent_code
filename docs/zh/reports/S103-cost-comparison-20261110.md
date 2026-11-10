# S103：暂停边界、固定任务对照与远端验证

执行 brief：`benchmarks/reference_briefs/S103-cost-comparison-and-smoke-boundary.md`。日期：2026-11-10。

## 剩余 smoke 改动审核

原未提交方案把含 `run status is 'paused'` 的非零返回纳入自动重试。该方案被撤回：日志文本不是稳定的执行边界，且 CLI 的 paused 可能返回 0，原分支不处理；启动新任务也不能替代待批准动作。

保留的修复是反向护栏：非零返回准备重试前，读取该工作区当前 run 的持久化状态；若为 paused，直接返回本次记录，即使日志别处含 timeout/TLS 等瞬时故障词也不重试。退出码 0 仍交给既有产物/运行状态验证，不直接证明成功。测试覆盖返回码 0/1 × 有无超时噪声四种组合，均只调用一次 run。网络重试、审批决策和暂停状态没有被自动放行。

## 同题对照

两版 Git 追踪快照均解压到本机 WSL Linux 文件系统、使用同一 Python 3.12.3 venv，同一已有本机路由，隔离工作区的 money.py/report.py/README/test_amounts.py 完全一致。相同 goal、auto 权限、auto 策略、no-research、max-iterations=3，顺序各跑一次。执行阶段两版均为 MiniMax medium。固定原测试 SHA256：`2633ec7e6ad445e3f699219a87ff1e4b91b24951a98e0a1f7be4073bd2963891`。

基线必须选 `48c08a4`：`37516da` 已含成本治理和评审修复，与当前再比较无法检验这些改动。两版还包含工具契约与评审差异，不能将结果归因到单条提示。

| 观察 | 48c08a4 | 37516da |
| --- | --- | --- |
| goal 耗时（不含显式 Review/Accept） | 46.52 秒 | 71.52 秒 |
| goal 阶段模型调用 | 4（含规划/收尾） | 9（含规划/收尾） |
| 显式 Review 追加调用 | 2（Zai 429 失败后回退 MiniMax） | 0（确定性评审） |
| 工具调用 / 失败 | 0 / 0 | 14 / 1 |
| 最终任务状态 | blocked，未写产物 | done |
| 独立既有测试 | 3 failed / 1 passed | 4/4 passed |
| 独立负数生成器/空集合/万项累加 | 失败 | 通过 |
| 原测试哈希 | 未变 | 未变 |
| Review / 接受 | fail，未接受 | pass / 1.00，workflow_state=accepted |

结论：新版在本次样本完成了任务，旧版在工具批次执行前被权限门暂停。旧版较少调用和耗时是提前失败，不能解释为更高效率；新版仍不能从单次样本证明稳定成本下降。旧版显式 Review 遇 GLM 额度错误，因此只对 goal 耗时与独立产物判据做直接比较，不声称跨 provider 对照通过。

证据位于 WSL `~/.cache/asteria-s103/`：两个 code 快照、两个 work 工作区（run 均为各工作区的 `run-20261110-0001`）、comparison.json、原始 goal/review/accept 日志。脚本初版读了不存在的 final summary completion 字段，因此 accepted 的汇总初值为 null；最终以实际 final_report_summary.workflow_state=accepted 和 accept 日志核对，不能把汇总空值误报为未接受。原始运行账本未改。

## 本地与远端验证

smoke 脚本相关测试 **23/23**，文档契约 **23/23**，Ruff 通过。`37516da` 已推送。精确 SHA `37516daadb694ea21c9c7876957e62bab595d956` 的 [Verify 42778375941](https://github.com/z243802480/mult_agent_code/actions/runs/42778375941) 中 Python 3.11/3.13 成功，Studio 在 Install Playwright browser 失败、UI 步骤未执行；不算整体通过。

公开 API 完整日志返回 403，公开步骤日志入口返回 404，能核实失败步骤但无法据此断言下载故障类型。为下一轮定位，浏览器安装步骤参照已有 Verify/UI 步骤将输出 tee 到日志、失败时把尾部加入 annotation，并保留真实退出码；没有增加跳过或软化失败。该修复与审核后的暂停护栏推送后，将按新提交精确 SHA 继续核对。

当前 ACTIVE_SLICE=S103；GLM 配额、数小时/大型仓库统计、长期成本稳定性仍为未关闭项。本轮不增加题目特例或绕过权限，不把缺 key 的 proof 当通过。

## 远端真实失败定位与修复

暂停边界/日志摘要更新已提交推送为 `ef30f47`。精确 SHA 的 [Verify 42779683568](https://github.com/z243802480/mult_agent_code/actions/runs/42779683568) 中 Python 3.11/3.13 成功，Studio 仍在浏览器安装失败。新增 annotation 经公开 checks API 提供了可核实根因：`ubuntu-latest` 已迁至 Ubuntu 26，而锁定的 Playwright 1.60.0 报 `Playwright does not support chromium on ubuntu26.04-x64`。此前不能读完整日志时未将其猜测为下载抖动。

修复仅将 `studio-frontend` 的 runner 固定为 `ubuntu-24.04`；本机安装的 Playwright core 也包含该平台依赖定义。Python 矩阵继续 ubuntu-latest，浏览器安装和全部 UI 测试保留，不添加忽略失败。Release 复用 Verify，因此同一修复也覆盖它引用的 UI 闸。其余 workflow 未发现浏览器安装步骤，不扩散改动。修复提交推送后继续按精确 SHA 核对结果。

## 最终验收与交接

代码修复已提交推送为 `bda18c4`。完整 SHA `bda18c4ef61c231c99914d1ba2743f6c1081f0a2` 的 [Verify 42780620068](https://github.com/z243802480/mult_agent_code/actions/runs/42780620068) 三 job（Studio、Python 3.11、Python 3.13）均 success，浏览器安装及 UI 测试步骤实际执行通过；前两次失败仍作为定位证据保留。本文与状态索引的后续提交仅记录该已验证代码 SHA 的验收结果。

S103 本刀收口：暂停边界修复、同题对照与精确提交的远端 CI 均有证据。没有把单次新版成功宣称为稳定降本，也没有把独立 provider 的额度失败当通过。下一步应先选择两版都能完成的固定任务，重复采样成功任务的耗时/调用数，再决定是否继续改提示或预算；较大仓库/数小时任务仍需独立验收。所有未跟踪验证目录、原 transcript 与本机路由均未入库。

S104 开工复核补充：旧版 task_execution_evidence.failure_type=policy_decision；decision-0001 原因是模型尝试 Git 命令并将输出重定向到工作区外 /tmp/test_amounts_baseline.diff，权限门正确拒绝。0 次工具调用不能解释为没有选择工具或无效 JSON 收尾，之前原因描述不完整，以此追加与原始 decision 账本为准。
