# S122 — 验收环境一致性与新链路真实证明

2026-11-11 用户「继续完成下一项」，承接总计划 §16.2 第 34 项。已读 AGENTS、总计划 §6/§16.2、S121 brief/report/本机记忆。保留 S121 拒收和暂停安装 decision，不恢复、不批准、不重跑旧目标。

## 参考与边界

复用 S121 的 [显式结构/类型与独立语义审计](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 参考、现有 GoalSpec 一次有界纠正与 canonical 产物投影。执行器固定已验收 `6e3be93`（Verify 43008738110 三 job 绿，Windows 1756 / WSL 106）。先不改产品，不增加模型输出上限、预算、权限或编排；真实缺陷才先确定性复现后窄修。实验/文档变更复用未变产品 SHA 的完整 CI，不重复无关全套。

## 新目标

从 S116 已接受 cachetools 源码产物复制不带 .asteria/缓存的新工作区，实现未跑过的 `Cache.partition_items(predicate)`，不是 S121 select_items 重跑。在一次 live peekitems 快照上逐项调用 predicate(key,value)，按 Python 真值把原始键值对分到 `(matched, rejected)` 两个独立新列表，分别保持原顺序/值身份；异常原样传播，回调修改缓存不改遍历快照。API 不计访问、不改变淘汰策略、不清理 TTL/TLRU 过期存储。保留所有既有行为。

必需：src/cachetools/__init__.py、docs/index.rst、NEW docs/分组（只读）.rst、NEW tests/test_partition_items_s122.py。仅允许修改、非必需：src/cachetools/keys.py。可选实现：NEW src/cachetools/_partition.py，仅实际需要才选择；不能拼条件到路径。原测试/其它源码/配置/LICENSE/旧 AGENTS 与公约不改。无网络、安装、秘密、其它实验/答案、执行器/安装包源码、人工解题提示或强制工具导航。

## 先预检再冻结

所有 baseline/命令/源码绑定均经**真实 RunCommandTool**（ShellGuard + 环境净化 + 进程围栏），工作目录与 Runtime 父进程环境相同：PYTHONPATH 只指执行器 src，不额外注入项目 src。pytest 使用公开显式 `-o pythonpath=src`，独立 oracle 和绑定命令使用公开显式 sys.path 引导。保存 requested/executed command、退出码和源码路径。此为真实命令工具，非完整 task gateway 重放；任务期另审所有工具记录与观察。

先核实公开 pytest/绑定绿、旧 oracle 绿、新 API 基线红；检查器正控制与副作用/分组反例也必须过。提前登记实际 resolver 档位，不要求或强制 session_agent。不满足即 0 模型调用停止，纠正实验设置后重新登记，不能带坏前置条件进入真实样本。

首次调用前冻结目标/公约/独立 oracle/执行器哈希并提交。一个真实目标，1800 秒外部上限和原预算；不修改输入或原模型产物、不反复采样刷绿。核对 typed intents 真实存在、必需/可选/许可分类与 canonical 投影、任务产物和最终严格范围、完整新旧 tests、源绑定/源码和执行器哈希、工具记录与唯一观察 ID、计量。自然观察 GoalSpec 有界纠正是否触发，未触发不能冒充恢复证明。

独立检查+人工输入/范围/源码审计均过且 native completed 才正式 Review→Accept；使用现有入口，不从外部调换报告或改 task/profile。失败保留。收尾同步唯一计划/ACTIVE/本机记忆。分钟级和单 provider 结果不外推小时级、独立 provider；keyed proof 仍 NOT RUN。

## 首次调用前登记

真实 RunCommandTool 的公开 pytest、绑定、旧 oracle 全绿，新 API 基线红；12 方法正控制绿，分组错误反例红。无额外项目 PYTHONPATH，原源码/执行器哈希不变、0 模型调用。实际 profile=harness（Harness profile required (high_risk).），不强制改档。冻结执行器为 6e3be93260d24beca2d27c4af02b48d30b52625a，输入 SHA256：

- contract.md: 93e50f50efe9d875311f750f8d7fd685c226eba6f4b693fd0922b9ce7f7741a8
- goal.txt: b8dfa86a43de532ca3d86496eb3780ef09d89f529745898a647ef0948a96bf68
- cachetools_partition_oracle_s122.py.txt: 4521eab3e3ffc013752b238f0326039ae8a1813c748ef1705f8a6877328cf040
- cachetools_peek_oracle.py.txt: f06d1df37efa1b2a7cf7a1576b71a1ae6f6e25b03dbdbaca5bd4056907b0e10e
