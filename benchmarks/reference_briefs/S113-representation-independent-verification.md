# S113 — 独立验收器去表示偏见

2026-11-11 用户授权两轮中的第二轮。已读 AGENTS、总计划 §6/§16.2、S112 brief/report 及隔离实验协议。真摩擦为 S112 的 53 个 oracle ERROR：计数器藏在验收器自己构造的原存储对象上，却从产品可能返回的包装对象读取它；公开契约从未要求包装器透传私有测试字段。

参考：[Anthropic 关于 agent eval 的官方工程说明](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) 强调 grader 可靠性与检查结果；本刀落实为测试持有自己的观测对象、判断行为而非解答内部布局。复用 unittest 与现有实验协议，不新增产品编排/维护命令。

## 范围与 DoD

1. 保留 S111/S112 原 oracle 原样，新增版本化 S113 oracle；公开契约及允许文件完全不变。存储计数/数据改由测试自持引用观察，不窥探被测实现私有字段、不尝试 unwrap 猜测。
2. 测试验证器本身：合法的不透传 writes 的存储包装能执行检查；确有副作用的写拒绝、回调执行、嵌套数据泄漏仍被拒收。正反例用小型确定性 test doubles，不提交真实实验解答。
3. 新 oracle 固定哈希、基线红/原测试绿后，新干净 TinyDB 上注册一次真实样本；执行器仍冻结 `1891f8e`，仅 src/schemas。与 S112 相同公开目标、pause 触发和共享 3600 秒/原预算；不读取旧解答，无人中途补提示/改代码。oracle 不进入目标。
4. 最终先独立原测试/固定 oracle、输入/范围/来源/读取审计与续作/计量连续性，再正式 Review→Accept。服务故障或真实语义失败仍红；如需后续修复，另留证据，不改本样本检查器刷绿。
5. 本刀只改实验验证与相关测试/文档，产品源代码不因检查器自身缺陷改变。跑 checker 回归、文档契约、Ruff 与合适 Linux 检查；复用未变生产 SHA 的精确 CI。同步总计划/ACTIVE 与本机记忆，旧 10 月路线评估改为历史快照。

预调用冻结：S113 oracle SHA256 `9e282df69c7994c821a0786a69be476f373d13e1eb0dd521b0859af620395788`；原公约哈希仍为 `31f05d93faf2a100d8d8054c487cc343ea83922505075963b38e58d7f22c6c18`。新样本目录为 `s113-tinydb` / `s113-1891f8e` / `s113-tinydb-20261111`，与旧样本分开。

回执：本刀已验收，检查器 8 项正反例通过，Windows 相关 31 / WSL 17 通过，9c7f014 的 Verify 42946426133 三 job 全绿。新真实样本 1049.27 秒，pause→新进程同 run，独立 oracle 20/20 + 全套 236 passed，正式 Review 1.00→Accept accepted；累计 91 真模型/315 工具，账本/目标/计量承接，范围/来源与读取审计通过。原 S112 红记录保持；完整边界/下一步见 `docs/zh/reports/S113-representation-independent-verification-20261111.md`。
