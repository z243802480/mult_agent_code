# S128 — 异常终止后的状态与累计计量恢复

2026-11-12。用户授权同批推进；已读 AGENTS、总计划 §6/§16.2 第40项、S126 报告与 Cancel/Resume/Execute/Budget/Metered 源码。

## 已证与待证

CancelCommand 明确是“进程已停后收尾”，活 writer 锁时等待6秒后返回 alive，不向运行进程发送取消请求。S126 控制器顺序为 cancel→SIGTERM，故906.52秒和 running 残留不能归咎 cancel 不工作；先在原快照副本测试 kill→cancel、正常 pause/resume、强终止→resume，不改原失败。

Execute 当前只用 cost_report 初始化 BudgetController，模型/工具调用在内存累加、任务/运行收尾写汇总；S126 强终止留下2模型/0工具，而完成账本为42/108。需要回放实际初始化路径判定是否可重建，不能从静态报告直接断言恢复已重置预算。

## 参考与约束

[Anthropic 长任务 harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)强调持久交接事实；本项目已有 JSONL 证据与 fsync+replace 的 JsonStore。复用现有原子存储和计量责任，不引入数据库/独立预算服务/新 maintainer CLI。S126 调用ID已不依赖行数，重建不得重编号或伪造历史。

## 实施边界

- 无模型回放保留源/账本前缀/任务，区分控制器顺序错误与真实产品缺口。
- 如果已证恢复只读旧汇总，最小接线让执行预算从持久事实恢复，并让后续计量在动作边界持久化。计量是调用尝试与预算，不宣称服务端账单；预留的在途调用和缺失usage必须显式保持未知，不能刷成已完成。
- 旧账本的 gate denied 与已计费失败不可盲目混算。证据不足时保守限制预算并标识恢复精度，不能伪造精确费用，不能把原报告回填成正常完成。新调用应记录可恢复的计量事实，覆盖成功、失败、权限拒绝、预算拒绝和技能/MCP。
- Cancel 的既有死进程收尾契约保留；若修其汇总只在确认 worker 已死后操作，不干扰活进程。Execute/Run 只允许当前责任链必要的窄接线，禁止顺手重构。

验收：原S126快照副本确定性重建、未来真实子进程强停/恢复、正常暂停恢复及预算边界回归；同批联合新真实目标与严格对账。旧S126整体拒收不改变；恢复工程通过与新目标接受分别记账。具体恢复字段/精度方案在生产修改前根据回放与现有schema继续细化到本brief。

2026-11-12 无模型预审已落盘 `~/.cache/asteria-evaluations/s128-recovery-20261112/preaudit.json`：实际 Execute._read_cost→Budget.from_report 只恢复2/0，原完成记录42/108。副本进程停后 Cancel 成功且幂等，除事件追加外工具/模型/观察前缀不变；原工作区仍保留 running。

具体方案：Budget.from_run 读取校验后的原报告与已完成模型/本地/技能/MCP账本，只取不降低计数的高水位，令执行入口使用该接口。工具记录可选 budget_charged 说明 registry/适配器是否实际调用预算计数（含预算拒绝）；本地前置 gate 拒绝不收费。旧 denied 缺该字段时按保守尝试计入并在可选 accounting_recovery 元数据标精度；旧模型缺 usage/预留但未记录调用也标记，不能冒充完整账单。模型 token 为已知下界/未知保持，不重写历史账本。根/包内schema同步。恢复后的预算绑定原子 cost_report 检查点，模型预留/真实usage/工具尝试在动作边界fsync+replace；超限异常仍保留已发生的尝试。未绑定的现有测试/独立预算对象保持内存行为，避免在子context把共享预算重绑到别处。Cancel只在确认writer已死且非既有settled时重建汇总；活进程/已settled不改。实际仅窄接 Execute 初始化与 Cancel 收尾，不作广泛重构。

跨进程新回归又复现：完成工具批后 os._exit(23)，预算预留已持久，但 resume 不调度遗留 in_progress 任务，直接返回 running。补齐同一恢复责任链：Resume 在现有 writer 锁内恢复未结束任务为 ready（不动 done/discarded、不在活worker旁改任务），并保留已发生工具事实供模型复核。复用已有 task_pause_checkpoint 在每个完成工具批的事件边界保存 stat 变化与进度，而非只等正常 pause；同任务/契约/当前磁盘签名匹配才能沿用，验证不复用。仅窄接现有回调和 Resume 门口，非新调度器。旧遗留无checkpoint的工作区不凭文件存在假造已完成改动。

副本回放结果：原S126源码/全部状态哈希不变，新的Cancel使副本cancelled，恢复42模型/108工具、82预算单位，tokens与完成记录对应；108条旧工具无budget_charged，按保守精度标记，不称原费用被精确追溯。跨进程强退出→真实Resume回归已完成同run，保留1次中断模型预留、只写一次工件、账本前缀完整。额外守住未初始化Resume不能因锁文件被隐式初始化；账本损坏时取消状态仍收尾、明确报计量恢复失败并保留原账本/费用。执行入口以外的规划/摘要/独立Review预算没有因此全部变成实时检查点，不宣称全生命周期断电计费完备。联合采样输入与限制见S127 brief。
