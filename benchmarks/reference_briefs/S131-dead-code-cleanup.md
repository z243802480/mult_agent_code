# S131 用户授权维护批：删除已失去调用方的私有代码

日期：2026-11-17。基线b5e32dd。用户本轮明确要求清理过时、不再使用的代码；属于S131主线旁的代码卫生维护，不改变S131语义/新鲜性待办或开启新编排波段。

已读AGENTS、研发总计划§6/§16.2与S131主brief。按本轮清理授权，仅从默认禁止宽泛重构的run/execute文件中删除逐项核实的无调用私有函数，不重排主路径或删除能力；其余清理同样限内部死代码。参考仓库既有ADR-0022/已删除登记：保留能力与单一实现，删除已被主路径替代的重复责任，不凭文件名或旧行号保留死实现。

## 审核清单

| 文件 | 删除候选（精确私有符号） | 保留的活实现 |
| --- | --- | --- |
| commands/run_command.py | _refresh_task_plan_eval、_task_plan_quality_bypassed、_active_task_plan_revision、_selected_decision_option、_task_plan_issue_codes、_task_plan_quality_decisions、_create_task_plan_quality_decision、_task_plan_issue_summary、_pause_run_for_task_plan_quality、_task_counts | _task_plan_quality_gate → TaskPlanQualityGate.check；质量报告/决定与预算暂停的活路径 |
| commands/execute_command.py | _agent_loop_max_rounds、_loop_quality_guard_config、_loop_continuation_requested、_mark_task_blocked、_refresh_harness_observations、_model_tool_call_summary、模块级_readonly_probe_read_path/_readonly_probe_list_path | model_driven_turn、当前迭代保险丝、自主环开关、验证/权限/工作器/工具证据 |
| commands/replan_command.py | _replan_count | _replan_lineage_root/_replan_lineage_count |
| core/runtime_profile_builder.py | _capability_adjusted_tier | _capability_adjustment与真实路由调用 |
| storage/audit_chain.py | _last_chain_hash | _chain_head，追加/重链/验证能力 |

初筛18个零静态引用叶节点；run内3个仅由死节点互相引用的私有辅助函数一并核实。全仓src/tests/scripts/Studio/benchmarks代码与配置查引用，另查动态getattr/setattr/导出注册；同名TaskPlanQualityGate._selected_decision_option是活实现，必须保留。历史报告/旧brief的引用不作为调用方，保留历史记录并在删除登记重定向。仅移除因此新增的未使用导入，修正直接相关过时注释/brief指针。

## 验收与边界

以精确AST节点清单删除，核对未删除的函数实现不变；不删除仍使用的公共命令、冻结占位能力、legacy持久兼容、schema或测试。清理当前批的真实调用链，若发现动态依赖则从名单撤回，不为删除而改测试。跑现有Run/Execute/计划质量/重规划/配置/审计链相关回归、Windows完整pytest、WSL相关与Ruff/类型/离线基准、文档契约。不新增只断言“函数不存在”的测试，不跑付费模型来证明纯删除。

所有实验现场、db、待批清理、账本和4001未知预留保持；不读取密钥/本机路由，不清缓存来伪造差异。完成后更新删除登记、计划与本机记忆，S131仍开放且下一项保持前置拒绝/验证新鲜性核实。提交前精确暂存清单与敏感路径/内容核查，按既有授权提交推送。

## 完成记录

21个候选全部通过引用核实并删除；2个未使用导入清理，生产净减236行。完整模块AST仅含清单节点/导入删除，gateway AST相同；活Canonical质量门同名方法保留。相关Win180/WSL157、完整Win2162过7skip42排除636.79秒、静态/文档23/五基准通过。无新增/删除测试，无新模型调用，主线状态与全部实验现场保持。详见[报告](../../docs/zh/reports/S131-dead-code-cleanup-20261117.md)。
