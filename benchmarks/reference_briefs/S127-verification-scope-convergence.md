# S127 — 验证范围、命令观察与收敛

2026-11-12。用户授权一次推进多个相邻任务；已读 AGENTS、总计划 §6/§16.2 第39–40项与 S126 原始 task/工具轨迹。先完成 S127，再 S128，联合真实目标验收；不并行代理、不扩编排。

## 已核实问题

S126 Planner 将整份 usage doctest 与用户必需 pytest 一起放入 planner_task 必过命令；旧文档原本不能整节无状态执行，模型后来已有新小节的独立通过证据仍绕行。不是 JSON 卡住，也没有 pre_final held_open 记录。RunTestsTool 仅把任意 shell 退出0叫做 Test passed；管道末端成功不能证明上游测试通过。整份文档执行在 cwd 生成3个未授权文件，原有 stat-level workspace_snapshot 已能观察，但工具结果没有把这些副作用反馈给模型。

## 参考与取舍

- [Anthropic 长任务 harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)：增量推进、实际测试、交接时干净环境。用在通用验证指导与工作区真实变化观察，不复制初始化多agent框架。
- [Anthropic harness 简化经验](https://www.anthropic.com/research/harness-design-long-running-apps)：验证 harness 假设、最小足够复杂度。不新增失败修复状态机或把每次诊断失败永久升为用户要求。
- [OpenCode 权限](https://opencode.ai/docs/permissions/)区分 shell 与 edit 资源；本项目 typed edit_boundary 不是任意 shell OS 隔离。复用已有有界 stat 扫描报告副作用，不重启本地强沙箱路线。

## 最小实施

1. 共享指导明确区分用户必需命令、对新产物的适当验证、可选诊断；计划不要把未确认适用的全仓/全文检查无依据升级必过约束。旧失败需基线证据、保留并报告，不能改 runner 或过滤输出造绿；成功范围已经覆盖时停止重复诊断。验证也遵守编辑边界，考虑文件/网络副作用，按授权安全隔离。
2. RunCommand/RunTests 报告真实 shell 退出状态与原输出，避免把任何0都命名测试通过。复用 workspace_snapshot 的有界 stat 扫描，反馈 created/modified/deleted 路径及 scan unavailable；不读文件内容，不自动删除，不据 stat 声称强隔离或测试语义。
3. 以真实工具用例验证管道失败被末端0掩盖时仅报告 shell 事实，验证命令创建/修改/删除文件时观察真实变化，权限/超时/大仓降级保持。通用指导经真实 GoalSpec/Planner/AgentHarness 提示通道测试，不加任务/模型/文件名特判。

验收：相关 Windows/WSL、完整 Python、Ruff/类型/离线基准；与 S128 同一冻结执行器做一个新真实目标，预登记输入、基线红/正控制绿、原预算权限，一个目标不重跑刷绿。独立执行示例/项目测试、严格范围、各通道身份和累计计量，全部过才 Review→Accept。S126 原失败/产物/状态不修改。原生代码块的通用呈现解析覆盖不由本次明确 doctest 采样冒充完成。

联合采样已具体化：从正式接受 S124 源码另复制，新增 Put counts example（put替换已存在文档+新增原先不存在文档），仅usage可改，验证后加载retrospect。此为新目标非重跑S126 remove目标；不声称成对因果比较。公开目标/隔离检查器见 `benchmarks/dogfood/tinydb_put_doc_goal_s127_s128.txt` / `tinydb_put_doc_oracle_s127_s128.py.txt`。900秒外部上限，控制器若到期先停进程、再调用既有Cancel做死进程收尾，明确不是给活worker发取消请求。
