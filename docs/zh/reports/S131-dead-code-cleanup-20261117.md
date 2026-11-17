# S131 用户授权死代码清理

日期：2026-11-17。基线b5e32dd。范围来自用户本轮“清理过时、不再使用的代码”；维护批完成后，S131主线仍是前置拒绝与验证新鲜性核实。

## 清理结果

| 文件 | 删除内容 | 私有函数数 |
| --- | --- | --- |
| commands/run_command.py | 已由TaskPlanQualityGate接管的旧质量门副本及未调用的任务计数 | 10 |
| commands/execute_command.py | 旧循环轮数/继续判断、质量配置、block辅助、观察重载、工具摘要及只读探针路径 | 8 |
| commands/replan_command.py | 无调用的_replan_count转发包装 | 1 |
| core/runtime_profile_builder.py | 无调用的_capability_adjusted_tier转发包装 | 1 |
| storage/audit_chain.py | 无调用的_last_chain_hash转发包装 | 1 |

共删除21个私有函数，函数物理行合计211；连同空行及2个失效导入，生产源码净减236行。gateway只修正两处指向已删除函数的注释。精确符号清单见[维护brief](../../../benchmarks/reference_briefs/S131-dead-code-cleanup.md)，替代关系见[删除登记](../已删除与已替代登记.md)。

初筛18个零静态引用叶节点，再核实run中3个仅被死节点调用的私有辅助函数。除代码扫描外，还搜索跟踪的Python/Studio/配置/脚本/文档引用及动态getattr/setattr、导出与注册路径；同名的TaskPlanQualityGate._selected_decision_option仍有活调用，保留。历史brief中的函数名/旧行号不作为调用方，两个直接过时brief加现状说明，其历史实证保持原样。

## 保持的实现与验证

逐文件比较删除前后的完整模块AST：差异恰好为清单中的函数节点和Execute中不再使用的ImportFrom；保留函数、常量、类定义及调用语句一致。gateway的AST完全相同。复扫未再出现满足本次保守条件的私有死函数，不宣称已经穷尽所有动态或公共兼容代码。

Run/Execute只做本轮授权的私有死节点删除，未顺手重构或格式化；计划质量门、模型循环、权限、重规划谱系、运行时路由与审计链能力保留。公共CLI、schema/持久记录和冻结占位能力保持，不删除测试或隐藏的维护命令，也不把有意未接线的repair独立计数当垃圾。

现有相关Windows回归180通过237.08秒；WSL相关157通过296.00秒。Ruff通过，类型检查无新增（60 known、18不再出现），五离线基准通过。完整Windows2162通过/7跳过/42排除636.79秒；测试数量与基线一致。未增加仅断言“函数不存在”的测试，也未运行付费模型来验证纯删除。

AST/全仓引用证明保存在本机Temp/asteria-cleanup-final-proof.json，初筛与精确删除清单见asteria-dead-code-scan.json、asteria-dead-code-cleanup-proof.json；相关日志前缀asteria-cleanup-。这些是本轮工程审计产物，不作为模型语义验收。

## 交接边界

本轮没有推进或重采S131真实目标。此前坏件漏检、最新正向paused/DECISION、db.json及decision-0001待批状态保持；实验现场、旧账本、旧DB/审批及4001未知预留均未做清理。原始证据不因代码卫生工作被签成通过。

下一步继续核实前置拒绝的可靠未执行事实与验证新鲜性/方法修订的关系，不只凭零计费/status推断，不代批删除或放宽守卫。执行计划、本机记忆与删除登记按本轮结果更新；远端Verify禁用时保持NOT RUN。
