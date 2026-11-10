# S110 规划错误反馈与独立仓库实跑

状态：本刀已验收。规划错误有界反馈通过回归与精确代码 CI；预注册 TinyDB 目标 223.26 秒完成，独立 oracle 12/12、原测试加新增回归 232 passed，正式 Review 1.00→Accept accepted。S109 两轮及解答暴露记录保持原结论；不外推数小时可靠性。

## 工程范围与证据

PlanAgent 初次收到不可用 JSON/任务形状/profile/schema 后，将限长响应和具体错误交回原模型重出完整计划，最多一次纠正。两次都走原解析、归一化和 schema；不扩大写权、默认预算或 transport，不猜修模型语义。混合非对象任务从原先静默过滤改为反馈错误。provider/预算异常不归类为格式错重试；MeteredModelClient 的真实预算拒绝测试确认只调用一次底层 provider，第二次留下预算失败记录。

PlanCommand 把每次失败、是否将纠正、成功纠正及最终 model/template 来源写入原事件/Inspector。原请求与目标不被改写，回灌前一响应最多 12000 字符、诊断最多 2000 字符；无效计划耗尽后保留原模板 fallback。参考见 S110 brief，不新增运行维护命令或编排。

最终生产提交 `2ffcbf7b397b412a76e7015cc4ea3e129e84acab` 的 [Verify 42845187042](https://github.com/z243802480/mult_agent_code/actions/runs/42845187042) 已完成，Python 3.11/3.13 与 Studio 三 job 全绿，完整 CI 覆盖更新后的计量期望。后续回执只改文档；keyed proof 仍 NOT RUN。

新增相关测试先红后绿。首次完整 Python 为 1626 passed / 7 failed / 3 skipped / 42 deselected（432.44 秒）；7 处失败均为既有计量/固定测试预算假设，多出的任务规划纠正确实计入调用与 token。更新测试期望及 compaction 用例的专用预算（4→5），产品预算不变，旁边的单次预算 hard-stop 用例仍为 1。修正后 compact/review/预算/计划定向 45 passed；更广相关 67 passed（8.57 秒）。Ruff src/tests/benchmarks 通过，mypy 棘轮无新增（60 项既有债，不改 baseline）。最终结论以精确代码 CI 为准。

## 实验预注册（调用前固定）

通用协议：`benchmarks/dogfood/isolated_repository_protocol.md`。目标是第三方 TinyDB，不再让模型修其执行器自身已有修复的历史代码；没有预制目标修复实现。

- upstream：`https://github.com/msiemens/tinydb`，MIT，保留原 LICENSE；commit=`edff96aeb2616402e9489d46e90a592c05565621`。
- 下载归档 SHA256=`99f6de856e39a5832a3e82fa75ec68150b4d20fb255dcffe82ede8597d725b6e`。
- 公共完整行为约定：`benchmarks/dogfood/tinydb_batch_contract.md`。仅修改 `tinydb/table.py` 的 update_multiple/imports/docstring，新增测试仅 `tests/test_batch_consistency_s110.py`。原测试、其他方法、配置与依赖保持。
- 单次迭代器完整覆盖所有文档；保留 document-major 顺序、后条件可见前修改、ID 顺序/重复。输入/条件/更新器失败时内存和 JSON 均无存储写入/嵌套残留，缓存仍有效；成功一次提交且缓存刷新，其他表和持久化不变。空/未匹配批次允许零或一次写入，避免对等价无操作过度约束。不要求任意 I/O 故障回滚或通用事务。
- 独立 oracle=`benchmarks/dogfood/tinydb_batch_oracle.py.txt`，SHA256=`ccf0aa88a12f8a9fb80f61de761e1cca7e6fd0136b1f04e835de14269161fc01`，12 个方法、Memory/JSON 子例。基线报告 8 个失败子例，属于 7 个方法，5 个方法已绿；旧测试 227 passed / 1 skipped（2.04 秒）。不在运行后修改判据，模型不读取隐藏脚本/结果。

Linux venv 没有 pytest-cov；上游 pytest.ini 的覆盖率参数初次导致命令退出 4。已在调用前明确检测并采用 `python -m pytest -o addopts= tests -q`，只取消不可用的覆盖率插件参数，原功能测试全跑，不安装、不改上游配置。目标必须核对导入指向本工作区。

执行器仅冻结 runtime package/resources 和 schemas，不复制本仓库的测试、benchmarks、控制脚本或参考实现。执行器、目标与外部验收分别放置；目标只含原上游源码/测试和公共指导。指令明确禁止越出工作区找解答、读取/反射执行器或安装库实现、其他实验与隐藏验收；正常 Python/pytest 允许。工具输入及文件范围另行审计；此为实验布置与行为约束，不称 OS 隔离。发生解答暴露即否决独立证明，不重开本地强沙箱路线。

## 真实结果与独立验收

WSL 普通 goal / auto / no-research / max-iterations=32，原全局预算不变、外部上限 3600 秒；223.26 秒正常完成，implementation + readonly verification 两任务，无重规划/暂停/解题提示/控制方改代码。goal 阶段 21 次 MiniMax-M2.7、58 工具/2 失败、执行协议纠正 0、compact 1，输入 636497 / 输出 16939 token；无模板回退。**规划首轮有效，未触发本刀格式纠正**，不把此样本称为真实 JSON 恢复样本。纠正成功/耗尽/预算拒绝的实际接线证据来自确定性集成回归。

独立固定 oracle **12/12**（0.111 秒），完整原测试加新增回归 **232 passed / 1 skipped**（1.58 秒），源绑定指向目标工作区；原有 227 项测试原字节不变。仅 `tinydb/table.py` 改动、新增 `tests/test_batch_consistency_s110.py`，其他原输入哈希不变，AST 确认 update_multiple 与 imports 外的节点不变，冻结执行器输入哈希不变。模型工具输入人工复核：文件读取/搜索均在目标，shell 只用于声明的 pytest 与目标 tinydb.__file__ 绑定核对；未观察到参考实现/执行器/隐藏验收读取，无网络/Git/安装/专家调用。此是已观察证据，不冒称 OS 隔离或任意程序不可越界。

模型新增 5 项有实质断言的回归；曾把应为 `[1,1,2,2]` 的 document-major 结果写成 `[1,2,1,2]`，看到失败后自行修正，没有按错断言改坏实现。其名为 generator 的成功用例实际用 tuple，成功的单次迭代器覆盖由外部固定 oracle 提供；生成器抛错的自建用例确为 generator。不以测试命名代替实际输入检查，也不为本例追加题目特化提示。

运行时默认 auto-accept 已在外部检查之前置 `accepted`，当时 `review_status=unknown` 且无 eval_report.json。它不等于正式 Review 通过。外部验收全过后，控制方用正常 CLI 补正式 Review（45.53 秒，pass/1.00、无后续任务/决定点），再 Accept，最终 `workflow_state=accepted`、`review_status=pass`。补验收后总调用 **22 次 MiniMax-M2.7**，输入 741488 / 输出 20982 token。额外一次是 Review，不是给解题模型的提示或修复续跑；解答修改/提示、暂停均 0。验收后再次核对原文件与冻结执行器，范围仍干净。没有将 TinyDB 解答复制回本产品仓库或发布上游。

## 证据位置与交接

目标：WSL `~/.cache/asteria-workspaces/s110-tinydb`；执行器：`~/.cache/asteria-runtimes/s110-2ffcbf7`；外部控制/验收：`~/.cache/asteria-evaluations/s110-tinydb-20261110`。run_id=`run-20261110-0001`，与 S109 不同缓存根，不混用。外部目录含 registration、原始 result.json、post-acceptance-audit.json、原输入/执行器 hashes、原始/独立测试日志及正式 Review/Accept 回执；原 result 保留 auto-accept 先发生的事实，补验收另记。Windows 临时目录保留归档/metadata、固定 contract/oracle 与单次 driver；控制脚本未打包进执行器或目标。

ACTIVE_SLICE=S110，本刀工程与已注册的有限目标验收完成。只证明一次约 3.7 分钟、单一生产方法的真实仓库目标；不能外推一到三小时可靠性、跨 provider 稳定性或复杂多文件自主交付。下一优先：沿用本协议选择更复杂的多文件目标并核实中断续作，不人为延长时长；代码只按新真实摩擦决定，开工前写新 brief，不扩编排 Wave/强沙箱。密钥留在正常本机路由，raw ledger/解答/既有未跟踪目录不入 Git。
