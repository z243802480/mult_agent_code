# S111 多文件目标与跨进程暂停续作

状态：工程修复已验收；真实多文件/计划暂停续作未验收。真实目标因 provider 过载在 0 工具/0 源码改动时 blocked；随后确定性跨进程回归复现并修复暂停改动证据丢失，Windows 全套/WSL 相关回归与精确 CI 全过。实跑执行器冻结在 2ffcbf7，未热改或重跑；S110 与 S109 历史结论保持。

## 调用前固定的范围

目标使用干净上游 TinyDB MIT 快照 `edff96aeb2616402e9489d46e90a592c05565621`，归档 SHA256=`99f6de856e39a5832a3e82fa75ec68150b4d20fb255dcffe82ede8597d725b6e`，不带 S110 解答。公共契约 `benchmarks/dogfood/tinydb_readonly_contract.md`，SHA256=`31f05d93faf2a100d8d8054c487cc343ea83922505075963b38e58d7f22c6c18`。

新增逻辑只读 TinyDB 句柄 API：read_only=True/不可变只读标记与公开 ReadOnlyError；文件缺失/冲突打开模式不得创建或破坏数据；默认/命名表变更在消费用户迭代器/回调之前拒绝；返回文档及查询输入不污染存储/后续读取；writable 默认与原测试保持。内部 helper/表示不固定，raw Storage/任意外部闭包/并发写/OS 隔离不在保证内。允许四个原模块与可选 errors.py，新测试仅 tests/test_readonly_s111.py；全原输入与新文件范围独立核对。

独立 oracle=`benchmarks/dogfood/tinydb_readonly_oracle.py.txt`，SHA256=`cebe977e317f6ee0f57f35824c3a57576466fe24de0c0c6a7227332450e8cc49`。基线 20 个测试方法报告 7 个失败、15 个错误（含子例，新 API 缺失），不是修复通过；原测试 **227 passed / 1 skipped**（1.53 秒）。Linux 使用既有 venv 的 `python -m pytest -o addopts= tests -q`，只覆盖缺失 coverage 插件选项，不改原 pytest.ini/功能测试、不安装依赖。

## 暂停与恢复方案

正常 goal / auto / no-research / max-iterations=32，初次与 resume 共用原预算及最多 3600 秒总窗口。观察首个非空允许源码变更后请求普通 pause，等待本轮进程退出和 paused；保存原目标/task/成本与实际账本前缀、已编辑文件 hash，确认未完成。随后马上使用新 OS 进程 `resume --session-id` 同一 run，不重发 goal，不改代码/补解题提示，不增加预算或停等凑时长。

检查实际两 PID/一个 run、目标未换、旧证据前缀保留、cost 承接且与调用日志对账、已编辑文件在恢复前未被清空；完成任务不倒退。若未真正暂停、参考解答暴露、预算/权限卡点或目标未完成，则对应验收不通过，不追加样本刷绿。暂停态不算完成，恢复阶段不算新的零成本样本。

目标、纯 runtime package/resources + schemas 和外部控制/oracle 分放；模型只获公共任务/指导，不获隐藏测试和控制脚本。人工审计模型工具输入与范围；不声称本地 OS 隔离。默认 auto-accept 若先发生保留事实，独立功能/原测试/范围与续作检查通过后才补正式 Review→Accept，不能把 accepted/unknown 当正式 Review。

## 真实样本结果

WSL `~/.cache/asteria-workspaces/s111-tinydb`，外部记录 `~/.cache/asteria-evaluations/s111-tinydb-20261111`，纯执行器 `~/.cache/asteria-runtimes/s111-2ffcbf7`。run=`run-20261111-0001`，PID 388，61.38 秒后 blocked。4 次调用均 MiniMax-M2.7，已报告 usage 为 input 6520 / output 5268（失败调用没有返回 usage，不当作零账单）；规划成功、无模板回退或格式纠正，首次 task_execution（约 9 秒）因 HTTP 529/overloaded_error 失败，之后生成关闭摘要。0 工具、0 源码/新测试改动、0 解题提示/控制方改代码、0 计划暂停、无 resume/Review/Accept。独立原测试 227 passed/1 skipped，因为目标未动；新 oracle 仍报告新 API 缺失，不可冒充实现成功。结果 JSON 中无检查点而为 false 的连续性标记表示“未测到”，不是已经证明账本丢失。

task_plan_eval 的 0.976/warn 只含 acceptance 数量 warning、0 error，并非本轮阻断点。代码核实 MiniMax 和通用兼容客户端已有 HTTP 5xx 有限重试及总 deadline；本轮未改 provider、529 判断词、重试次数或预算，没有再调用模型重跑刷绿。

## 通用续作缺陷与工程修复

补真实子进程集成回归，用确定性客户端隔离外部 provider：初进程通过正常 CLI 请求 pause，活动工具批完整写入 `checkpoint.py` 后停在回合边界；新进程用 ResumeCommand 恢复同一 run，只读文件并执行原声明验证，不再写文件。原实现的正例失败：文件/账本/成本保留，验证 1/1 绿，完成契约却称 required changed artifact was not produced。负例将工件值改坏后验证红，原门正确阻断；不能把此问题归因于 529。

修复仅沿用现有磁盘快照的 `(mtime_ns, size)` 签名：正常用户暂停时经 JsonStore/双份 `task_pause_checkpoint` schema 记录当时实际修改；run/task/任务契约 hash 相同且当前签名仍匹配才承接。承接项继续走原 write_scope 与 unscoped_changed_files 分流，不复用旧验证、不打开全局 verified-noop。任务契约变化、文件变更/消失、损坏或不合 schema 检查点、大工作区快照不可用均保守不承接；多次暂停合并仍有效的早期改动，完成后清理本任务检查点。检查点名按 task_id hash 生成，不拼接未约束的 task_id 为路径；事件只记引用和数量。它是 stat 级进度证据，不是文件内容完整性/OS 隔离证明，不读取工件或秘密内容。

`execute_command.py` 只在用户暂停记录、完成判定合并及成功完成清理三处接线；新 helper 管理类型化检查点，预算与权限配置不变。正例确保全程只一次 write_file、执行模型仅初次 1 + 恢复 2 次，账本保留原字节前缀、同 goal/run、累计调用与 token 对账；完成后检查点已清理。负例仍非 completed。schema/跨契约/跨 run/多次暂停/不可用快照等单位正反例及原控制/预算/文档首批 **44 passed**；随后加入大批 rename delta 的保守退化测试，WSL 对最终代码的暂停/检查点/预算相关 **22 passed**（26.81 秒）；Windows 完整 Python **1642 passed / 3 skipped / 42 deselected**（541.58 秒）；两个 routing 警告来自原确定性路由单测，非真实样本使用 fake。Ruff src/tests/benchmarks 与 mypy 棘轮无新增（60 项既有债，不改 baseline）。

## 精确代码回执

生产提交 `1891f8ef6ad67c3465d44f99ca6ad7059501c75e` 已推送；[Verify 42942385587](https://github.com/z243802480/mult_agent_code/actions/runs/42942385587) 已完成 success，Studio/Python 3.11/Python 3.13 三 job 全绿。两份 checkpoint schema 字节一致；最终文档契约 23 passed。该 CI 与确定性进程测试证明工程修复，不补成旧真模型目标成功；keyed proof 仍 NOT RUN。后续回执仅文档，不改生产代码。

## 交接

ACTIVE_SLICE=S111。工程续作修复已收口；真实多文件/计划暂停续作仍未验收，下一优先是在服务稳定后以 1891f8e 冻结执行器、另立记录再测同类多文件与真实 pause/resume，不修改本轮失败。当前不增加第二个真实样本。不做模型/题目/错误词特化，不开编排 Wave/全局写并发/本地强沙箱。密钥、第三方解答、raw ledger 与既有未跟踪验证目录不入 Git。
