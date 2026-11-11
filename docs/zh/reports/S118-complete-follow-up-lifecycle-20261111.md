# S118 — 完整续作生命周期的新自然目标

2026-11-11。本轮真实追加目标及生命周期验收通过，新正式 Review 1.00→Accept；S117 的原失败不改写。本轮也观察到两次自动重规划和重复验证，列为后续核对项，不能把成功结果外推为无摩擦或小时级可靠性。

## 预检与冻结

执行入口为总计划 §16.2 第 30 项。最初注册的 TinyDB snapshot 目标在调用前发现：S113 是 harness profile，现有 assess_session_continuation 只接受 session_agent。保留 `s118-follow-up-20261111/preflight-not-run.json`：**NOT RUN，新增模型调用 0**；未改旧 profile 或放宽续作入口。TinyDB 公约/检查器保留为未运行的预登记资产，不沿用它们的检查计数。

改用已独立接受的 S116 工作区隔离副本，追加新的 `snapshot(deep=False)` 不可变检查映射 API（不是 S117 peekmany 重跑）。沿用 cachetools v6.2.1、MIT、上游 commit `ca7508fd56103a1b6d6f17c8e93e36c60b44ca25`。这是有历史产物的自然追加需求，不是新的从零仓库解题。

- 执行器 `eb7679c`，只导出 src/schemas；新试验登记提交 `7a1b175`。
- 公开公约 `benchmarks/dogfood/cachetools_snapshot_contract_s118.md` SHA256 `96cb862b3ecdf7aff8a59ec0486f900d6b514230377c0431ff5fcd703afc17de`。
- 外部 oracle `cachetools_snapshot_oracle_s118.py.txt` SHA256 `86b9ff0bbf8b76aeb8b814b2277e436dd2f8d030716132e498713bc1d260057b`。
- 目标 SHA256 `2fef463591343d3dcdfcce780b572d399b6725dbcbb4a700c37af0f46f91d348`。以上均在首次调用前冻结；新 oracle 12 方法因缺 API 出现 59 个 subtest ERROR，旧 oracle 15/15、原测试 264 过。

公开行为涵盖不可变成员、浅引用/深值隔离、跨值共享引用和循环、key 身份、深拷贝异常、TTL/TLRU 单一时间/过期不清理及原访问策略。检查器接受自定义不可变 Mapping 与标准代理，不限定内部类型；6 项正反例过。TinyDB 检查器另有 11 项正反例，不能当其真实目标已跑。

## 工程修复

开工先坐实一个通用 warm/cold 写范围差异：flat 布局的 `tinydb/database.py` 在冷规划能获授权，warm 只给 src-layout 通用占位而被拒绝，确定性 1 红 6 绿。新增纯 `observed_directory_write_scopes`，冷 planner 与 warm 准备共用实际观察到的顶层目录规则，不按包名特判、不沿用旧目标具体文件授权。秘密、隐藏、依赖/构建目录排除与 PathGuard 保留。未新增并发、编排或维护命令。

Windows 完整 **1716 passed、3 skipped、42 deselected**；相关 Windows 首轮 95 过，检查器扩展后纳入完整套件；WSL 最终相关 72 过（首轮 62 后纳入全部新检查器用例）。Ruff/类型棘轮无新增错误（60 项既有基线）。`eb7679c` 的 [Verify 42987610282](https://github.com/z243802480/mult_agent_code/actions/runs/42987610282) Python 3.11/3.13 与 Studio 三 job 全绿。flat 目录写修复本轮是确定性证明，不能用 cachetools 的 src-layout 真跑冒充 flat 真写证明。

## 真实运行与独立验收

普通 `goal --continue-session`，同一 `run-20261111-0001`，无控制器解题提示/改代码/人工暂停，不提高或重置预算，3600 秒外部上限。实际 **667.63 秒**，新 oracle **12/12**、旧 oracle **15/15**、全部 **308 tests**（原 264 + 新 44）通过，来源绑定、允许范围、原工作区和执行器哈希通过。

只改 `src/cachetools/__init__.py` 与 `docs/index.rst`，新增 `tests/test_snapshot_s118.py`；其余原输入不变。人工解析全部 110 新工具输入，检查 shell、补丁、最终源码/文档/测试；未发现答案、运行时源码、安装包实现或相邻实验读取。

入口快照及正式接受后复核均确认：

- 旧 task-0001 全字段不变；原 goal 字段保持，normalized_goal 追加本次需求。
- 新 task-0002 初始 acceptance 对应本次指令，verification_policy 清空旧命令/回读路径。
- 旧 eval/review/final 四报告原字节归档；新正式 Review 前活跃 eval 缺席，最终执行摘要 review_status=unknown，没有沿用旧 pass。
- 模型/工具/观察/events 账本字节前缀保持，累计预算连续。新 39 次真实模型（38 执行 + 1 收尾），全部 MiniMax-M2.7，24→63；新增输入/输出 1,580,292 / 25,054，最终累计 2,335,793 / 43,071，与 cost_report 精确对齐。
- 新调用/观察均 110，串行 ID 一一对应；工具累计 43→153。新 denied=0、failure=2，不把无拒绝样本当拒绝路径已真跑。

独立检查和人工审计之后，新正式确定性优先 Review pass/1.00（0.67 秒），Accept accepted（0.41 秒），未新增模型调用。原生 auto-accept、正式 Review/Accept、外部独立验收分别记录；这次三者均符合各自条件。

## 自主恢复与仍有的摩擦

模型先用不兼容补丁格式失败，随后改用 shell；有一次复合 shell 的编辑脚本失败，但后续 sed 让整条命令退出为 0，模型通过回读发现未改，再修正插入位置。新增两条 timed-cache 测试的过期夹具有误（2 failed/37 passed），模型自己修正，无外部解题介入。最终源码未保留误插入 FIFOCache 的临时方法。

执行中 task-0002→0003→0004，前两者 discarded、最后 done：第一次契约仍有早期专用测试命令的失败；后来的成功是包含编辑与 pytest 的不同复合命令，不能凭字符串或“看起来全套”推断已覆盖同身份失败。第二次已直接验证成功，却被要求新 changed artifact；最后 verify-first 修复没有新增源码改动即可完成。实际证据为两次 run_blocked/task_replanned；新增一次 context_compacted 是最终 handoff，不是压力压缩实证。旧 task 不受重规划影响。

这暴露了后续值得核对的通用问题：完成前应给模型明确的未闭合验证身份；验证已有产物时不应逼它制造无用 diff。先核实 session 的同任务反馈与恢复契约，不吞不同命令的失败，不按模型名/错误词放行，也不以限制复测次数代替正确性。

新增测试仍有质量边界：LFU 用平局淘汰断言，RR 的未触发 choice 夹具不正确。固定独立 oracle 用非平局频率及真实 RR 淘汰避免这些盲点，未修改模型原测试刷绿。Sphinx 未安装，未声称文档构建通过。

读取测量：57 次成功 read_file、45 个 next_offset、4 次严格“下一次同路径”匹配，partial_line=0；payload 均 ≤6000 字符。精确参数+可见 payload 相同的重复 3 次，13,652/238,873 字符；对照 S117 为 2 次、8,784/241,452 字符。只证明发生，不证明因果节省或全部回看无用。最后文件修改为 toolcall-0103，后续两次全套、两次专项、两次来源绑定均成功，无新源码改动；重复验证与恢复关联需进一步复现。

## 证据与下一步

WSL 工作区 `~/.cache/asteria-workspaces/s118-cache-snapshot`，外部审计 `~/.cache/asteria-evaluations/s118-cache-snapshot-20261111`：登记/哈希、入口快照、旧账本前缀、冻结新旧 oracle 日志、人工审计、读取/验证度量、pre-review-result 与最终 result 均保留。原 S116/S117 工作区不改写。

下一优先复现上述完成前验证反馈和 verify-first 恢复契约，再按真实摩擦窄修；flat 包的新 session 真写/追加需求仍待独立取样，不迁移旧 harness 会话。单次约 11 分钟不证明一至三小时可靠性，独立 provider 未验收；GitHub keyed proof 保持 NOT RUN。
