# S114 — Review 重复表示去重与读取归因

2026-11-11，承接总计划 §16.2 第 26 项。brief：`benchmarks/reference_briefs/S114-review-context-and-repeat-read.md`；代码提交 `aa3e4f035319773dae71832055070bb2ff688365`。用户授权的下一步是先诊断上下文开销，再修可证实的通用问题。

**结论**：Review 的重复表示已修；对相同已完成任务的单对真实额外评审，输入 165,255→110,773 token（-32.97%），两次都 pass/1.00。未改验证判据、权限、预算或执行循环，没有按模型/TinyDB 写特判。Windows 完整 1655、相关 55、WSL 32 已过，精确提交 CI 三 job 已绿；本刀已验收。

## 实际归因

使用原 S113 只读账本重建 Review context，不调用 provider、不改原目标；路由健康取原 eval_report 的已记录字段，未读取/输出本地 keys 或 routes。统计与临时捕获在本机 Temp `asteria-s114/`；重建包含已有 Review/Accept 的后续记录，因此是**离线重建对照**，不冒充首个真实请求的逐字节捕获。

按原 ReviewAgent 的 indent=2 JSON 格式，630,807 字符：

| 区段 | 字符数 |
| --- | ---: |
| trajectory | 522,517 |
| 其中 tool_observations | 341,920 |
| 其中 tool_calls / model_calls / events | 42,816 / 42,116 / 34,837 |
| 顶层 tool_observations | 56,379 |
| task_plan / goal_spec | 14,105 / 12,449 |

现有选择仍是 trajectory 最近 50 条与顶层最近 12 条工具观察，并非全部 315 条。focused 模式保留这些详细证据，低风险 slim 的旧裁剪规则也未改变。问题在于选中的观察同时带外层/内层相同 summary、相同 command/requested_command、由完整 data 再渲染的 payload；与输出无关的格式空白也重复占用输入。

## 修复与边界

`context_slimming.project_review_evidence` 只投影给 Review 模型的观察列表：

- 外层 summary 与 observation.summary 精确相同时，只保留内层一份。
- observation.data.command 与 requested_command 精确相同时，只保留 requested_command；不同则两者保留，不能掩盖命令被改写。
- payload 只有与现行真实工具 renderer 从保留 data 生成的结果**逐字相等**时才移除；独有诊断、read_file 的唯一文件内容、无法重建的旧数据全部保留。
- 附投影说明与删除计数；不删任何已选观察记录、错误/状态/returncode、完整结构化 stdout/stderr 或截断标记，不重写原始账本。目标及用户数据不递归改写。

在 `ReviewAgent._request` 统一接入（包含注入 model_client 和 focused/high-risk 路径），JSON 使用紧凑空白序列化；确定性评估与 `_normalize` 仍消费原始 review_context。没有修改 completion contract、CorrectnessEval、slim/focused 的风险路由、schema、execute/run 或任何预算。

同一离线重建输入去掉 62 个重复摘要、40 个重复 command、31 个可重建 payload，再压缩 JSON 空白：630,807→409,667 字符（-35.06%），本机投影约 0.0023 秒。**字符比例不是 token/计费比例**；实际用量另由下述真实对照确认。

新增 5 个参数化回归实例覆盖 focused/slim、真实失败和 returncode 保留、只存在于 payload 的文件字节不丢、不同 actual/requested 命令不合并、原上下文不原地修改、真实 Review 请求接线及失败/缺验证的既有降级语义。缺验证仍是 score=None / unverified，不把本刀偷换成新的评审政策；失败 correctness_signal 仍 fail。

## 单对真实额外 Review（不是新自主目标）

调用前已登记：原 S113 已接受工作区复制为两个初始文件 hash 完全相同的副本，继承 91 次模型调用与原预算，不重发 goal、不改解答。A 冻结 1891f8e；B 冻结 aa3e4f0；两执行器仅导出 src/schemas。先 A 后 B，各普通 review 一次，不为刷绿重试。

原始 registration、原目录 hashes、两个 stdout 日志与 result：WSL `~/.cache/asteria-evaluations/s114-review-pair-20261111`。目标副本在 `~/.cache/asteria-review-workspaces/s114-before` / `s114-after`，冻结执行器在 `~/.cache/asteria-runtimes/s114-review-before` / `s114-review-after`。

| 项 | 旧版 A | 新版 B |
| --- | ---: | ---: |
| 真实模型/provider | MiniMax-M2.7 | MiniMax-M2.7 |
| 新增 Review 调用 | 1 | 1 |
| provider 真 input_tokens | 165,255 | 110,773 |
| provider 真 output_tokens | 2,268 | 3,242 |
| 本地 context_estimate | 160,871 | 104,876 |
| CLI 耗时 | 35.38 秒 | 23.46 秒 |
| overall | pass / 1.00 | pass / 1.00 |

本次真实输入减少 54,482 token（32.97%）；输出长度和耗时也不同，不把一次对照扩成稳定端到端降本或美元费用结论。两副本源文件/执行器 hash、goal_spec、原 JSONL 前缀均保持，用量由 91→92 正常承接且与各新增账本相符。原 S113 **整个原目录的文件 hash 未变**，原验收与成本记录不改写；没有新增 autonomous goal 或再次 Accept。两个 cost_report 的 near_limit 仍带历史上下文压力，不拿它当新版请求的实时 token 比率。

## 执行/恢复重复读取：观察到什么

S113 原轨迹中，179 次 read_file 有 27 次路径与非空 payload 都与此前完全相同；40 次 payload 被 6,000 字符渲染限额截断。初段 149 工具/92 次文件读取，重复 11、字符截断 20；恢复段 166 工具/87 次文件读取，重复 16、字符截断 20。shell stdout 的底层截断两段各 4 次。分页 offset 实际生效，例如请求 offset=390 后内容确从 390 行开始，**不能诊断为分页没接线**。

这些统计不能证明每次重复都是无用工作：可能是恢复后重新定位、代码变化、历史输出压缩或模型自行复查；没有捕获每轮完整 messages，不能凭次数归因。另确认输出可见性有真实改进空间：whole-file header 可显示 `lines 1-None`，大型请求窗口 header 显示请求的结束行，而后续字符渲染可能截掉后半段。下一刀应针对**实际可见范围与续读提示的诚实性**先写确定性正反例；保持原输出预算，不靠增预算/硬限读/催促模型解决。该执行侧修复不夹带进本刀 Review 投影，也不宣称已降低自主执行总调用量。

## 验证与 handoff

- Windows Review/去重/最新验证/预算 fallback + 文档契约：55 passed。
- WSL Review/去重/最新验证/预算 fallback：32 passed。
- Ruff 通过；mypy ratchet 无新错误（60 条既有 baseline，未改 baseline）。
- [Verify 42951272391](https://github.com/z243802480/mult_agent_code/actions/runs/42951272391) 在精确代码 aa3e4f0 上 Studio / Python 3.11 / Python 3.13 全绿。
- Windows 完整 pytest：**1655 passed / 3 skipped / 42 deselected**，441.37 秒；两条既有混配路由 fixture 告警，无新失败。

执行总计划、ACTIVE 镜像和本机记忆同步 S114。后续主线为 read_file 可见范围与续读提示，小时级/独立 provider 的可靠性仍未证明；GitHub keyed proof 继续 NOT RUN。原六批未跟踪验证输入、实验 raw JSON/模型轨迹、私有 routes/keys 不纳入提交。
