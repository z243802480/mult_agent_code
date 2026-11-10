# S111 多文件目标与跨进程暂停续作

状态：已预注册，尚未调用模型。沿用未改的生产代码 2ffcbf7，其 Verify 42845187042 的 Python 3.11/3.13 与 Studio 全绿。S110 只证明单方法约 3.7 分钟，S109 失败/解答暴露历史保持。

## 调用前固定的范围

目标使用干净上游 TinyDB MIT 快照 `edff96aeb2616402e9489d46e90a592c05565621`，归档 SHA256=`99f6de856e39a5832a3e82fa75ec68150b4d20fb255dcffe82ede8597d725b6e`，不带 S110 解答。公共契约 `benchmarks/dogfood/tinydb_readonly_contract.md`，SHA256=`31f05d93faf2a100d8d8054c487cc343ea83922505075963b38e58d7f22c6c18`。

新增逻辑只读 TinyDB 句柄 API：read_only=True/不可变只读标记与公开 ReadOnlyError；文件缺失/冲突打开模式不得创建或破坏数据；默认/命名表变更在消费用户迭代器/回调之前拒绝；返回文档及查询输入不污染存储/后续读取；writable 默认与原测试保持。内部 helper/表示不固定，raw Storage/任意外部闭包/并发写/OS 隔离不在保证内。允许四个原模块与可选 errors.py，新测试仅 tests/test_readonly_s111.py；全原输入与新文件范围独立核对。

独立 oracle=`benchmarks/dogfood/tinydb_readonly_oracle.py.txt`，SHA256=`cebe977e317f6ee0f57f35824c3a57576466fe24de0c0c6a7227332450e8cc49`。基线 20 个测试方法报告 7 个失败、15 个错误（含子例，新 API 缺失），不是修复通过；原测试 **227 passed / 1 skipped**（1.53 秒）。Linux 使用既有 venv 的 `python -m pytest -o addopts= tests -q`，只覆盖缺失 coverage 插件选项，不改原 pytest.ini/功能测试、不安装依赖。

## 暂停与恢复方案

正常 goal / auto / no-research / max-iterations=32，初次与 resume 共用原预算及最多 3600 秒总窗口。观察首个非空允许源码变更后请求普通 pause，等待本轮进程退出和 paused；保存原目标/task/成本与实际账本前缀、已编辑文件 hash，确认未完成。随后马上使用新 OS 进程 `resume --session-id` 同一 run，不重发 goal，不改代码/补解题提示，不增加预算或停等凑时长。

检查实际两 PID/一个 run、目标未换、旧证据前缀保留、cost 承接且与调用日志对账、已编辑文件在恢复前未被清空；完成任务不倒退。若未真正暂停、参考解答暴露、预算/权限卡点或目标未完成，则对应验收不通过，不追加样本刷绿。暂停态不算完成，恢复阶段不算新的零成本样本。

目标、纯 runtime package/resources + schemas 和外部控制/oracle 分放；模型只获公共任务/指导，不获隐藏测试和控制脚本。人工审计模型工具输入与范围；不声称本地 OS 隔离。默认 auto-accept 若先发生保留事实，独立功能/原测试/范围与续作检查通过后才补正式 Review→Accept，不能把 accepted/unknown 当正式 Review。

## 交接

ACTIVE_SLICE=S111，当前仅实验与文档改动，无新增产品行为或预算变化；文档契约 23 passed。出现新 runtime 摩擦才先复现后窄修，不做模型/题目/错误词特化，不开编排 Wave/全局写并发/本地强沙箱。密钥、解答、raw ledger 与既有未跟踪验证目录不入 Git。后续补实际运行 ID、进程、检查点、独立结果与正式验收回执。
