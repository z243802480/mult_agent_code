# S118 — 完整续作生命周期的新自然目标

2026-11-11 用户「继续下一批」，承接总计划 §16.2 第 30 项。已读 AGENTS、总计划 §6/§16.2、S117 brief/report、S113 的真实 TinyDB 历史及现行续作入口。S117 原红样本不改写、不重跑。

## 参考与目标

复用本项目冷 session 的“观察到的顶层目录 + 通用产物”写范围，以及 S117 的新任务/新判据/结果归档/累计预算机制。参考此前已读的 [Anthropic 上下文工程](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) 的按需读取和持久进度；不写模型认知分支，不新增编排、并发写或维护命令。

本轮从已独立接受的 S113 TinyDB 工作区创建隔离副本，为它追加只读数据库快照导出 API `snapshot(table_names=None)`（新目标，不是上游已有 API）。以调用者持有的原存储引用、Document 公共接口和文件字节观察快照/副作用；旧 readonly oracle 作为兼容闸。完整公开公约、新独立检查器与目标在首次调用前冻结哈希，先证新 API 基线红、旧测试/旧 oracle 绿，再正常 `goal --continue-session` 同 run 追加任务。

## 开工核对与边界

TinyDB 是 flat package 布局。当前冷 planner 会把观察到的真实包目录加入写范围，warm follow-up 却只有通用 src-layout 占位，可能在必要写入时误拒绝。先用真实权限策略确定性复现；若坐实，只共享冷/暖已观察目录的 scope 构建规则，保持秘密/运行时/依赖目录排除与 PathGuard，不沿用旧目标的具体文件授权，不按 tinydb 名字特判。

真实运行保留旧任务全文、原 goal 字段、各账本字节前缀及累计预算；新 criterion 只对应追加指令、无旧验证残留；旧 Review/final 报告须原字节归档、执行期不得沿用旧 pass。运行前后的源码/范围/来源/执行器和原工作区哈希、工具调用与观察 ID、真实路由、固定新旧 oracle 与原全套均审计后，才另行正式 Review→Accept。

不提高/重置预算，不给解题提示、强制工具路线、人工暂停或计时填充；外部上限 3600 秒。外部答案/oracle/控制器/运行时或安装包实现/相邻实验访问均拒收。真实失败保留，通用缺陷先红→窄修→绿，不再追加本题采样刷绿。单轮数分钟不外推小时级/独立 provider；keyed proof 保持 NOT RUN。

## 验证与交接

新增检查器测合法等价表示和真实错误反例；产品变更跑相关 Windows/WSL、Ruff/类型棘轮及精确 CI 完整检查，避免不变代码反复全量。记录读工具成功/拒绝、续读提示和重复读取（先测量，不按模型补丁）。最终更新总计划/ACTIVE/报告及本机记忆，明确原生 auto-accept、新正式 Review 与独立接受三者的边界。

## 预调用登记

flat 包写入误拒绝已复现 1 红 6 绿；冷/暖共享 observed_directory_write_scopes，保留现有目录排除和 PathGuard，不继承旧具体文件。相关 Windows 95 / WSL 62（检查器扩展前）通过，检查器最终 11 项正反例通过，Ruff/类型棘轮无新增。

- `tinydb_snapshot_contract.md` SHA256 `a37795d66e921b28c13830b8695730b44f581596fda8e22d5fe3b1d24463cd40`。
- `tinydb_snapshot_oracle.py.txt` SHA256 `c5b8c81ff331c5fe0429c431d968d12d0cc698cbaf43b9df30cf70a7c6a7212f`。
