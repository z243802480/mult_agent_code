# S112 — 新版多文件与跨进程续作实证

2026-11-11，用户授权两轮中的第一轮。登记 brief：`benchmarks/reference_briefs/S112-real-multifile-resume.md`，提交 `647f999`；调用前本地文件已冻结，登记提交在初轮执行中完成。生产运行时为 `1891f8e`，未改源码；其 Verify `42942385587` 的三个 job 全绿仍适用。

## 结果及边界

**同目标、多文件、跨进程续作和计量连续性通过；整体独立功能验收未通过，不能称完整自主目标已验收。** 原测试加新增回归 246 passed / 1 skipped；冻结 oracle 运行 20 个方法，出现 53 个 ERROR，均为 `ReadOnlyStorage` 没有验收器自定义的 `writes` 属性。这是验收器表示偏见，尚不能据此判断对应语义正确或错误。没有运行正式 Review/Accept；运行时自身 auto-accept 的 accepted 单独记录，不冒充独立接受。

公开契约明确不规定内部表示，允许通过包装器实现逻辑只读。原 oracle 在 `seeded` 将自定义计数存储交给 TinyDB 后，却通过返回的 `db.storage.writes` 观察计数，误把内部对象恒等关系变成必需 API。应由测试保有自己创建的底层存储引用，直接观察写入/数据。**本轮原 oracle 和红色日志保持不变**；修正须登记 S113，并先以合法包装与坏行为反例验证，不能偷偷重判本轮为绿。

## 冻结与实跑

上游/原始归档、公约与 oracle 哈希见 S112 brief（均与 S111 相同）。新目录相互分离：

- 执行器：WSL `~/.cache/asteria-runtimes/s112-1891f8e`（仅 src/schemas）。
- 工作区：`~/.cache/asteria-workspaces/s112-tinydb`。
- 外部原始证据：`~/.cache/asteria-evaluations/s112-tinydb-20261111`，含 registration/result、before/production hashes、原始运行/验收日志、checkpoint 账本副本。

基线原测试 227 passed / 1 skipped，oracle 因未实现 API 为红。一次普通真实 goal：`run-20261111-0001`，MiniMax-M2.7，默认已有真实 medium 路由，无独立 provider 样本。首个非空改动为 `tinydb/errors.py` 后正常 pause，初轮 PID 390、226.20 秒；暂停态 25 次模型调用。新 PID 419 正常 resume 同 run，448.00 秒；合计 674.20 秒，无凑时长。

最终 3 个任务完成，修改原四个生产文件（database/table/storages/__init__），新增 errors.py 和 tests/test_readonly_s111.py。新增测试含写拒绝前迭代器/回调未执行、JSON 字节不变、嵌套读取/缓存隔离、存储 factory 和默认可写行为，非仅空断言。全套 246 passed / 1 skipped；source binding 为当前工作区，所有原文件对账无越界，冻结运行时哈希未变。

暂停前五份 JSONL 账本前缀保留，goal_spec 字节不变，只有一个 run；研究任务的 done 状态保留，原工件未由控制方更改。最终 cost 与原始账本精确一致：60 次模型、203 次工具、输入 2,510,242 / 输出 44,604 token。2 次 context_compacted；记录字段 protocol_errors=5 不等于纯 JSON 错误计数，不能据此断言 5 次 JSON 失败。工具失败 5 次（两次 patch 格式/上下文、三次测试非零），模型自行修复后本地测试通过。无 replan 或规划 fallback。

已逐项归类 203 条完整 input_summary：137 read_file、18 search_text、1 todo_read、4 todo_write、14 run_command、13 apply_patch、1 write_file、11 run_tests、4 list_files；全部可解析。文件读取仅本工作区原源码/测试、公约和生成测试；全部 17 种命令为本地公约/源码读取、工作区 find、声明解释器 pytest 与 import 来源打印。无父目录/相邻实验/运行时源码/参考答案读取记录。控制方解题提示与代码编辑均 0；正常计划暂停 1 次、暴露停止 0 次。

这证明一次约十一分钟的真实跨进程续作，不证明一到三小时可靠性、独立 provider 或整体功能独立验收。S111 的 529 单轮失败保留，不因本轮服务恢复而删除。

## 下一轮

S113 修独立 oracle 对内部表示的误约束，增加合法包装/真实坏行为的检查器回归；公开行为/编辑范围不放宽。新 oracle 在新 goal 前固定、干净上游重新运行，不复制本轮解答。仍按原协议检查同会话续作与独立 Review/Accept。用户要求的本机记忆更新随第二轮回执收口。
