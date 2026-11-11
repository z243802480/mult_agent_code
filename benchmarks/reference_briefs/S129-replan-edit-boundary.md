# S129 — 自动重规划的编辑授权继承

2026-11-12，用户一次完成几个相邻任务授权。本批第三项来自S127/S128新真实摩擦，非新编排Wave。已读总计划§6/§16.2、S125/S127/S128 brief、ReplanCommand与现有typed边界实现。

## 证据与参考

冻结49602ba的一次新真实目标449.44秒后原生paused：初任务有restricted/usage，自动生成的task-0002/0003缺edit_boundary，原GoalSpec上限仍在。ReplanCommand._task_from_failure只复制read/write_scope，漏复制typed上限。删除验证副产物被现有常开高危guard拦住，审批不绕过；原源目录/日志/决定不修改。

复用 [OpenCode edit/shell资源分离](https://opencode.ai/docs/permissions/)及本项目S125结构化权限方案：修复延续目标授权，不由规划任务扩大权限。目录/精确路径仍是既有literal规则，不按错误词、模型或任务名称特判；不重启强沙箱。

## 最小修复与验收

先在真实快照副本用现有生产_task_from_failure重放无模型证缺字段。新修复任务继承父任务边界，且与当前持久GoalSpec上限取交集；父缺字段时从GoalSpec恢复，双方均无字段时保留旧兼容。父/目标上限open不抹掉另一方restricted；无交集为restricted空。复用现有validate_edit_boundary与write_scope交集，不新造路径语义。无效结构失败关闭。原acceptance/验证/只读恢复规则不顺便改；同类源上限字段消费点排查，不凭缺字段猜旧目标限制。

测试两代重规划、父更窄/目标更窄、文件/目录交集、空上限、旧字段兼容、无效边界、真实写工具拒绝越界。原S127快照模型账本/GoalSpec/目标文件哈希保持；这只是确定性生产重放，不冒充旧实跑已被修成成功。与前两项最终完整回归、Ruff/类型/WSL、精确源码CI一起收口，联合目标仍按原结果拒收，不批准删除操作、不补一轮模型刷绿。

防止逐个任务制造者漏接：交集放到现有task_contract纯函数，Replan持久化时复用；Execute._execute_task入口再用当前GoalSpec绑定一次，即使别的旧节点漏字段或声明open，也不能通过文件工具扩大用户授权。不新增RuntimeContext字段或逐工具读GoalSpec，不改模型认知/验证要求；中央入口仅增加一次纯投影，旧无typed目标兼容。
