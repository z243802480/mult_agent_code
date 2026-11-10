# S107 任务契约传递与完整目标自主解题

状态：RUNNING，尚未完成独立验收。用户关注目标下持续自主解题，不要求固定运行时长。

## 已完成的工程修复

PlannerAgent 的任务输出加入 read_scope / validation_commands；归一化保留模型声明的只读上下文及局部验证，不再只从产物反推读范围或总是复制全局验证策略。缺省旧格式仍按原方式工作。原任务指导及产物路径保留，只读依赖不加入 write_scope，PathGuard 的保护路径规则继续生效。

提示要求模型让每任务检查在该任务及依赖完成后即可通过，把完整目标验收放在实现之后；不按题目硬改任务图或命令。模型仍可能规划不佳，所以这不是正确性保证；GoalSpec 没有删除全局验收，目标是否完成另由独立整套检查判定。

本地规划/执行/重规划/profile 回归 108 passed；新增契约测试覆盖实际 task schema 存储往返、runtime context 传递、只读路径不赋写权限、保护路径仍拒绝和旧计划回退。Ruff 通过，mypy 棘轮无新增错误。

## 完整目标实跑

输入存于 benchmarks/dogfood/boardkit_goal/：依赖标准库的本地任务板骨架，要求完整持久化 CRUD、乐观并发控制、评论、幂等、原子快照导入导出、CSV、localhost HTTP 和 CLI。原始 53 项验收冻结，初始 40 failed / 13 errors。另用 65 条记录的状态机、组合过滤/分页、过期版本、评论、删除、无效导入原子性、快照往返、16 路幂等创建和 CSV 独立检查需求。

WSL Ubuntu / Python 3.12，隔离工作区 ~/.cache/asteria-s107/board-workspace，run-20261110-0001。代码冻结在 ~/.cache/asteria-s107/code-frozen（基线 a8807fd 加本刀两个生产模块修改），运行时不跟随仓库后续编辑。完整目标文本、冻结输入哈希、进程起点分别为 goal.txt / before-hashes.json / goal-process.json。外部驱动及 oracle 位于 Windows 用户临时目录 asteria-s107-board-*.py。

本次进程临时关闭未配置的 strong/cheap 档，回退既有 medium / MiniMax；路由探针确认没有 fake，未迁移或输出凭据。普通 goal / auto / no-research / max-iterations=32，最多 3600 秒，默认预算 200 model calls / 1000 tools 等保持。完成可提前停止，不凑时间。运行期间不手改解答、不替模型拆题或追加纠错提示；遇安全/预算边界如实停下。

初始观察：模型自行规划六任务，已读规范；存储、格式、HTTP、CLI 及最终集成分别拿到所需 README/源码/测试读范围和阶段命令，最终任务保留完整 tests/ 检查。该观察证明接线可达，不证明目标已经成功。

## 交接

ACTIVE_SLICE=S107。待运行结束后核对 result.json、独立原测试及 oracle、范围外变化和原哈希，统计实际问题修复、重规划/压缩/协议纠正与人工介入。只有这些通过才计自主完成；如果提前失败/停在预算边界，保留失败而不盲目重跑。

本刀不直接恢复 S106 的失配任务图；保留其暂停现场。S106 的长任务整体失败与混合 fake 路由结论不改。既有未跟踪验证目录、本机路由与凭据不入库。原生工具消息/流式通道仍不在本刀翻默认。
