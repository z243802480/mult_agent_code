# S116 — 独立真实目标与读取范围/账本修复

2026-11-11，用户「继续下一步研发计划」。brief：`benchmarks/reference_briefs/S116-independent-cache-inspection.md`；预注册/验收器 `da179b4`，工程修复 `c29c55c`。**真实目标与两处通用工程修复均已验收；Windows 完整 1682、相关 79、WSL 56 通过，精确修复 CI 三 job 全绿。**

## 真实目标与固定输入

执行器冻结 `f4311536b3f30026964a676475de338e2807a39b`（仅 src/schemas）。新目标为干净 cachetools v6.2.1，commit `ca7508fd56103a1b6d6f17c8e93e36c60b44ca25`（MIT），不是最新版声明。归档 SHA256 `74a81ab41704515b4c33c87f01e5db3ad024ac24653a0472715b6745567aca33`。

新增 peek / peekitems：检查标准七类缓存时，不改变访问频次/最近使用/插入顺序，不调用读取/missing/随机淘汰/大小/TTU 副作用；时间型缓存按一致时刻过滤过期项，原过期存储留给显式 expire。同步文档与新增测试，内部表示不限，原测试/配置/其他源码/许可证不变。

公约 `benchmarks/dogfood/cachetools_peek_contract.md` SHA256 `42c0baf4c91a8f4a2cda27708750e6177a79fc4f9c900b2ce5ccf7d5aca3c49c`；独立 oracle `cachetools_peek_oracle.py.txt` SHA256 `f06d1df37efa1b2a7cf7a1576b71a1ae6f6e25b03dbdbaca5bd4056907b0e10e`。调用前固定；原测试基线 220 passed，oracle 15 方法因缺 API 为红（53 个 subtest ERROR）。检查器 8 项自验允许等价 pair 表示/不透明对象，拒绝遗漏/重复/值身份错误/过期项被提前删除，不依赖产品私有布局。

目录分离：WSL `~/.cache/asteria-workspaces/s116-cachetools`、`~/.cache/asteria-runtimes/s116-f431153`、外部 `~/.cache/asteria-evaluations/s116-cachetools-20261111`。外部保存 registration、goal、原输入/执行器哈希、原始日志、pre-review-result、人工输入审计及最终 result；oracle/控制器未放入目标。无解题提示/人工改代码/计划暂停，原 3600 秒外部时限与 200 模型/1000 工具等既有预算保持。

## 运行与独立验收

一次普通 goal，`run-20261111-0001`，PID 387，MiniMax-M2.7 实路由；**171.82 秒**。模型修改 `src/cachetools/__init__.py` 和 `docs/index.rst`，新增 `tests/test_peek_s116.py`，未创建可选 helper。没有规划 fallback/replan；1 条 context_compacted 事件为既有收尾流程，不据此认定发生过压力恢复或降本。

| 检查 | 结果 |
| --- | --- |
| 固定独立行为 oracle | 15/15 方法通过，覆盖七类缓存、真实淘汰顺序/副作用、时间边界、timer 一致性、datetime、显式 expire |
| 原全套 + 新回归 | 264 passed（原 220 + 新 44），原测试哈希保持 |
| 范围与来源 | 只有允许的两处原文件修改和一处新测试；导入来自目标 src/cachetools；执行器原文件哈希保持 |
| 人工输入/源码/文档/新测试审计 | 执行命令均限当前工作区读取、修改、测试和声明的来源绑定；未发现外部解答/相邻实验/运行时或已安装包源码访问记录 |
| 正式 Review | 外部检查与人工审计之后显式执行，**deterministic-first pass/1.00**，0.67 秒；没有新增模型评审调用 |
| 显式 Accept | accepted，0.42 秒；不拿先发生的 auto-accept 代替独立接受 |
| 计量 | 含正式评审仍为 24 次真实模型调用、输入 755,501 / 输出 18,017 token；cost 与原模型账本精确一致、within_budget |

执行账本有 43 条（36 shell、4 run_tests、3 todo_write；其中 2 条失败）：首次新增测试暴露跨类私有 marker 名字改写错误，随后一次修改脚本执行后的测试仍有 14 红/30 绿，模型继续自行修正，最终全部通过。另有两次 registry 前读取拒绝，详见下节；不能把 43 条当成全部工具尝试。

人工审核确认新增测试包含实际 API、容器/值身份、hook 不调用及过期行为断言。质量边界也保留：其中 LFU 平局断言有移植性局限，RR 回调 fixture 没有覆盖其真实淘汰路径；独立 oracle 专门避开 LFU 平局并检验实际 RR 插入/淘汰。Sphinx 未安装，文档只核实内容与范围，未宣称 docs build 通过。不提交该实验生成的解答或原始轨迹。

## 关键补审：不是“从未尝试 read_file”

只看 tool_calls 会误判为模型全程主动选 shell。完整 tool_observations 实为 **45 条**：除上述 43 条外，还有读取 AGENTS.md、TASK_CONTRACT.md 的两个 `ToolPermissionDenied`；它们在 registry 前失败，没写 tool_calls，分别重用后续调用的 toolcall-0001 / toolcall-0002。

因此正确结论是：**尝试 read_file 2 次、成功 0 次，next_offset / partial_line 没有实际触发**。不能据此证明 S115 提示被采用或无用，也不能证明全部 shell 选择都因拒绝。完整审计修正在独立的 `observation-audit-correction.json` / `result-with-observation-audit.json`；原始运行记录和预审结果保留。中途沟通中“未调用 read_file”的早期判断已纠正，不作为最终结论。

任务原始 read_scope 为 `home/administrator/`、`Sphinx/Ruff/mypy/`。原因不是按文件名拒绝：whole-session builder 原本设置空 read_scope（该层不限制工作区读取），但 execution_preferences 把从目标文字提取的目录提示加进去，错误地把“不限”变成有限 allowlist。普通环境说明也会产生路径样式提示，从而让必要指导文件被错挡；shell 读取未受这一 task 范围门约束。这一层本来就不是 OS 强隔离。

## 最小通用修复

1. `execution_preferences.py` 保持空/未设置 read_scope 的原语义：额外目录提示不能把它收窄。已有非空范围仍保留原范围与既有显式新增目录规则；不按 AGENTS/TASK 文件名白名单放行，不增加写权限，PathGuard/秘密/越界保护不变。
2. `tool_execution_gateway.py` 将本地 registry 前门禁拒绝通过既有 record_tool_call 记为 denied 尝试。registry 拥有的执行记录不重复；同一串行 gateway 中下一工具不再重用该 ID。拒绝没有执行工具，原执行预算不虚增；账本的尝试数与实际进入 registry 的执行数需分开看。没有新建状态机、编号服务、schema 或维护命令。

确定性回归在原冻结 f431153 上 **4 failed / 1 passed**；修复后读范围语义与真实 ToolRegistry/gateway 流程通过：拒绝→成功读取→真实工具失败三条记录 ID 分别 0001/0002/0003，观察可一一对齐，没有重复执行记录，实际工具计量为 2。正反例还确认限定范围继续阻止无关读取、PathGuard 继续挡秘密及父目录。

原已经验收的真实目标仍在 f431153 上，不重跑刷绿、不改 oracle、不改写旧 task 合同；**新工程修复没有新增真模型采样证明**，以确定性/完整回归与精确 CI 单独签收。

## 工程验证与下一步

- Windows 相关 runtime/检查器/文档共 79 passed；WSL runtime/检查器共 56 passed。
- Ruff 通过，mypy ratchet 无新增错误（60 条旧 baseline 保持）。
- 检查器预注册 `da179b4` 的 [Verify 42966905816](https://github.com/z243802480/mult_agent_code/actions/runs/42966905816) 三 job 全绿；修复 `c29c55c` 的 [Verify 42969469061](https://github.com/z243802480/mult_agent_code/actions/runs/42969469061) 三个 job 全绿（Studio / Python 3.11 / Python 3.13）。
- Windows 完整 pytest：**1682 passed / 3 skipped / 42 deselected**，451.25 秒；两条既有路由 fixture 告警，无新失败。

下一刀优先在修复后的执行器上预注册新真实目标/自然需求变更，观察读范围、尝试记账和新版反馈的真实路径；不强迫导航、不凑时长、不把 171.82 秒单例扩大为小时级可靠性或稳定降本。独立 provider 仍未验收，keyed proof 保持 NOT RUN。

总计划、ACTIVE 镜像与本机记忆已按最终证据同步；原六批未跟踪验证输入、私有 routes/keys、实验解答和原始运行轨迹不纳入提交。
