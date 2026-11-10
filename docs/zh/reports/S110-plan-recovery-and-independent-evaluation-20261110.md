# S110 规划错误反馈与独立仓库实跑

状态：工程接线与定向回归已过，精确代码 CI/真实目标尚未验收。S109 两轮及解答暴露记录保持原结论。

## 工程范围与证据

PlanAgent 初次收到不可用 JSON/任务形状/profile/schema 后，将限长响应和具体错误交回原模型重出完整计划，最多一次纠正。两次都走原解析、归一化和 schema；不扩大写权、默认预算或 transport，不猜修模型语义。混合非对象任务从原先静默过滤改为反馈错误。provider/预算异常不归类为格式错重试；MeteredModelClient 的真实预算拒绝测试确认只调用一次底层 provider，第二次留下预算失败记录。

PlanCommand 把每次失败、是否将纠正、成功纠正及最终 model/template 来源写入原事件/Inspector。原请求与目标不被改写，回灌前一响应最多 12000 字符、诊断最多 2000 字符；无效计划耗尽后保留原模板 fallback。参考见 S110 brief，不新增运行维护命令或编排。

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

## 当前交接

ACTIVE_SLICE=S110。先通过定向、完整 CI，再按已固定定义做一次普通 goal，最多 60 分钟/默认预算；无解题提示或控制方代码修改。独立原测试/oracle、范围/原输入哈希和参考暴露审计通过才接受；若自动接受先发生，外部验收仍有独立否决权。不得以运行时 Accept 替代独立验收，不按时长凑数或刷样本。密钥留在正常本机路由，raw ledger/解答/既有未跟踪目录不入 Git。
