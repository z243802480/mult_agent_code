# S129：重规划及执行入口的目标授权上限

2026-11-12；[brief](../../../benchmarks/reference_briefs/S129-replan-edit-boundary.md)。源码 `e0fffc1a32ffaf792b33ab82407f1306a2a97850`；本批第三项，不新增编排或用户命令。

## 结论与修复

**编辑授权继承工程验收通过；原联合真实目标仍拒收。** S127/S128目标的父任务及持久GoalSpec有限改usage的typed上限，ReplanCommand生成的task-0002/0003却缺该字段；原write_scope仍限制usage，没有宣称本次文件工具已成功越界。shell验证生成3个文件属于另一个已知边界，typed路径guard不是任意shell的OS隔离。

修复将父任务与当前GoalSpec的编辑上限取交集，持久化到修复任务；父缺字段可从当前GoalSpec恢复，双方均无字段保持旧兼容。open不抹掉restricted，无交集为restricted空；无效结构失败关闭。目录/精确文件沿用既有literal路径规则，复用task_contract.write_scope，不按模型、任务或错误词猜授权。

交集放在现有task_contract纯函数；Execute._execute_task入口再次绑定当前GoalSpec，旧节点漏字段或声明open也不能通过文件工具扩大目标授权。重规划与消费点共享同一规则，避免逐个制造者打补丁。原验收要求、只读恢复、验证命令和高危删除guard未放松，未增加RuntimeContext字段或逐工具读GoalSpec。

## 验证与诚实边界

在原真实快照副本直接调用生产_task_from_failure，无模型先证child缺字段；修复后两代child/grandchild均保留restricted/usage。原工作区源/运行状态/GoalSpec/工具与模型账本哈希不变，未批准或执行pending删除。是确定性生产重放，不是修成了旧实跑或新增真模型目标。

15条新回归覆盖父/目标更窄、目录/文件交集、空/旧/非法上限、两代继承、只读恢复、真实写工具拒绝越界，以及真实Execute入口处理遗漏上限的旧任务。相关Windows72 passed/1 skipped，WSL73通过；Windows跳过的是已有目录链接能力用例。最终三项完整Windows1864 passed/5 skipped/42 deselected（571.71秒）、Ruff(src/tests/scripts)/类型无新增/五离线基准通过。

最终源码的 [Verify43072934506](https://github.com/z243802480/mult_agent_code/actions/runs/43072934506) Python3.11/3.13、Studio含UI均success。没有以远端CI通过替代真实目标验收；keyed proof、独立provider与小时级可靠性仍未证明。

证据：WSL `~/.cache/asteria-evaluations/s129-replan-boundary-20261112` 的 `red.json` / `green-final.json` / `source-hashes.json`。原联合目标报告见 [S127](S127-verification-scope-convergence-20261112.md)，原S126失败也不重编号或回填。

下一项S130为模型自拟验证方法的证据化修订：原Planner脚本语法错误，替代小节检查已通过，重规划仍继承错误具体方法。应保留用户/项目要求并区分来源，研究有失败及替代检查实证的审计修订机制；不把不同命令的0当原命令修好，也不以放松所有门禁或Python特判绕过。
