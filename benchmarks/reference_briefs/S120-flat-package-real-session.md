# S120 — flat 包新会话与自然追加真实采样

2026-11-11 用户「继续研发」，承接总计划 §16.2 第 32 项。已读 AGENTS、总计划 §6/§16.2、S119 brief/report、本机交接、未运行的 S118 TinyDB 公约与检查器，以及入口 profile 和续作条件。

## 参考与冻结边界

复用本项目已验收的普通 goal/session、观察到的顶层目录写范围、pre_final 反馈、严格重验和累计预算；参考此前已读的 Anthropic 上下文/工具工程，以工具事实引导模型，不规定解法或导航。运行时固定 `4c6cb98`（精确 Verify 42995602110 三 job 全绿、Windows 1728/WSL 137），只导出 src/schemas。

输入为 S113 已接受的 TinyDB readonly 源码产物（MIT，上游 edff96aeb2616402e9489d46e90a592c05565621），复制时不带旧 .asteria/运行历史，从 init→普通 goal 新建会话。不是新干净上游解题，也不是迁移旧 harness profile；原 S113/S118/S119 工作区及证据不改写。

## 两阶段新目标

1. 新会话：`TinyDB.snapshot(table_names=None)`，公开行为保留原只读 API、单次 storage.read、独立 Document/嵌套数据、选择/缺表/空表语义。版本化 S120 公约，复用 S118 中尚未真跑的冻结 snapshot oracle（11 方法、11 正反例）。先核实本次新 API 基线红、原 236 测试和 readonly oracle 绿；不沿用旧预检计数。
2. 仅在第一阶段独立检查、人工范围/输入审计、正式 Review→Accept 通过且 assess_session_continuation 支持时，追加 `snapshot_counts(table_names=None)` 表计数摘要。复用相同选择和单读/无副作用语义，不构造 Table/Document；另有调用前冻结的公开公约与独立 oracle。模型自主选择实现，原第一阶段测试保持不变。

两阶段都在首次调用前预注册完整目标/范围/检查器哈希，共用 3600 秒外部上限与原预算，不重置/提高计量。第二阶段从原 run 继续，核对原任务/目标/账本前缀、新判据和 Review 新鲜性，不手改 task/profile。第一阶段不通过或入口不支持就保留原结果，不重跑刷绿、不绕过入口。

## 验收与停止条件

执行器、目标、外部控制器/oracle 分目录。先检查器合法表示/副作用反例，再真实目标。每阶段核实原输入/执行器/来源/允许文件、原全套与固定独立检查、实际工具/观察 ID、provider、累计成本与权限；人工审计后另行正式 Review/Accept。无 controller 解题提示/改代码、强制工具策略或人工暂停；禁止答案/运行时或安装包源码/相邻实验/秘密/网络访问，出现暴露则拒收独立证明。

观察 S119 未闭合命令反馈、严格重验/无需新 diff、读取提示和自动 replan 是否发生；未触发就如实记录，不强制造红，不比较不等价任务宣称降本。通用运行时缺陷先确定性复现再窄修，原样本保留。仅实验/文档时复用未变生产 SHA 的 CI，跑检查器/文档与 WSL 回归；若改产品才新增完整检查/精确 CI。

收尾更新总计划/ACTIVE/本机记忆。单次分钟级采样不证明一至三小时可靠性；独立 provider 未验收，keyed proof 仍 NOT RUN。

## 首次调用前的冻结登记

普通目标入口静态预检为 session_agent；实际落盘 profile 仍以真跑核实，不手改。检查器 Windows 42 项（含文档 23、原 snapshot 11、counts 8）过，Ruff 过。全部目标/检查器在首次调用前固定：

- `tinydb_snapshot_contract_s120.md` SHA256 `cedf6d21e781bd5021aae1abea7b6e8be98f485a41c5b7357b70a6f6a32bf05c`。
- `tinydb_snapshot_oracle.py.txt` SHA256 `c5b8c81ff331c5fe0429c431d968d12d0cc698cbaf43b9df30cf70a7c6a7212f`。
- `tinydb_snapshot_counts_contract_s120.md` SHA256 `8af93fdfa7885a977fc5087af017cb34feee7a017f5b3e3ca8a61f7dbae28c3d`。
- `tinydb_snapshot_counts_oracle_s120.py.txt` SHA256 `8a62b2c56ad12b031dc9620dcc2d7bac502a098e8646ed51cc7f6dff693afb32`。
- `tinydb_readonly_oracle_s113.py.txt` SHA256 `9e282df69c7994c821a0786a69be476f373d13e1eb0dd521b0859af620395788`。
- `asteria-s120-goal.txt` SHA256 `c7a1caf4c57db96267bcc46d0b0c681cb5839688c5a781762530e99b9e554524`。
- `asteria-s120-follow-up.txt` SHA256 `9d9372b4d0e8a25a6feeaacd631e22d8adb64419435b3fd32eaba1902d62e325`。

## 首轮发现后的窄修范围（不修改冻结采样）

第一阶段功能检查全过，但多建了 `tinydb/_snapshot.py（仅在实现需要时）`，严格范围失败；因此第二阶段 NOT RUN，不做正式 Review/Accept、不重跑原目标刷绿。证据链为 GoalSpec 把可选实现写进 target_outputs → Planner 把说明拼进 expected_artifacts/expected_changed_files → 两次 pre_final 缺失产物反馈 → 模型创建该字面路径。

本刀只纠正 GoalSpec/Planner 通用提示：允许修改的范围不等于必须交付，可选方案/条件保留在说明或约束，必需路径字段只放精确字面路径。保持现有缺失产物守卫和 Unicode/标点文件名支持，不按本次路径、语言、provider 或后缀改解析器，不放宽范围验收。以缺失/存在的合法 Unicode 路径回归保护守卫；另做隔离的有限真实规划诊断（原目标/旧 GoalSpec，最多两次请求），不执行工具、不改原实验、不算原样本通过。产品提示有改动则完整 Windows 检查、WSL 相关回归与精确生产 SHA 的 CI。
