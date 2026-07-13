# Slice — 自主环默认绑定权限档(set-and-forget 第一刀)

承低负担缺口地图(`docs/zh/notes/低负担-set-and-forget-缺口地图.md`)#1 最大杠杆 + 用户 2026-07-13
授权"绑定预设"。目标:让"设好权限就自动开发"真兑现,消掉失败即停问人的强制 `resume`。

## observed_pattern(行业已验证)
- **Claude Code / Codex / OpenCode**:一次设好权限模式(CC allowlist·Codex suggest/auto-edit/full-auto·
  OpenCode permissions)→ 自动开发连跑 → 只在计划 + 高危打断。失败**自纠**不停下问人。
- 权限模式=承诺的自主度;选了"自动"档就该真自动,而非选了档还每次失败 block 交还人类。

## asteria_mapping(我们怎么做)
- **根因**:三自主环(`auto_repair`/`auto_replan`/`auto_replan_goal`·S78/S79/ADR-0017)后端全闭合但
  **默认全关**——任一任务 blocked → `run_command.py:1336` 停在"可 resume 边界"等人敲 `resume`。
  即"权限设置已达 CC 水准,但选了档它却不真自动"。
- **修**:新增 `core/permission_policy.py::autonomy_rings_default_on(mode)`——`auto`/`reviewed_auto`
  → 三环默认 ON;`ask_everything` → OFF;缺失/未知 → 视作 reviewed_auto → ON。三处判定
  (`execute_command._auto_repair_enabled`/`_auto_replan_enabled` 读 `policy["permission_mode"]`·由
  `apply_run_config` 从 run_config 盖入;`run_command._auto_goal_replan_enabled` 读
  `self.permission_level`)默认改为随档解析。**显式 `agent_loop.<ring>` flag 仍覆盖**(逐字节可回退)。
  删两份 `policies.default.json` 的 `auto_repair:false`(让它随档解析而非被显式 false 钉死)。
- **边界不减配(ADR-0016)**:环只管**失败恢复**,不碰权限;高危 shell/deploy/push 仍由常开硬门暂停;
  预算保险丝/recovery-cycle 上限/lineage cap/DecisionPoint 升级原样兜底。`ask_everything` 完整保留
  逐步监督。`asteria plan`(默认 ask)保持 plan-first 监督;`asteria run`(默认 balanced)现自动开发。

## 影响与验证
- 爆炸半径小(execute 套件经 PlanCommand 默认 ask→不变):仅 3 条 run_command opt-out 测 + 1 条
  acceptance 测受默认翻转影响。处理:3 条 pin `permission_level="ask_everything"` 保原 opt-out 意图 +
  改写 flag 测为随档语义 + acceptance 断言接受 `discarded`(环自取代 blocked 是合法新终态)。
- **新测**:`autonomy_rings_default_on` 单测(auto/reviewed_auto/balanced→on·ask_everything/ask→off·
  None/未知→on)+ 集成 `test_run_command_auto_replans_blocked_task_by_default_under_reviewed_auto`
  (默认 reviewed_auto 下 blocked 任务**自动 replan 不停**·final_report 含 `replan: completed`)。
- 全量 **1216 passed**(仅 6 条既有失败·clean HEAD 同红·无关)·ruff 净·mypy 零新增。
- 真栈:环在真栈可用已由 [[ring-realstack-validation-A]] 证(武装态);本刀=把武装态设为**默认**,
  默认下 fire 由确定性集成测坐实(避免昂贵非确定性失败复现 + editable-install 陷阱)。

## do_not_copy(禁止照搬)
- 不动高危硬门/预算保险丝/lineage cap(环只管失败恢复非权限·安全不减配)。
- 不翻 `parallel_writes` 全局默认(独立 DecisionPoint·仍冻结)。
- 不砍 `ask_everything` 的逐步监督(显式 opt-out 完整保留)。

## 实现记录
- date: 2026-07-13
- notes: §16 v1.2.27 + 缺口地图 #1 勾掉 + 记忆 `low-burden-set-and-forget-ux`/`handoff-continue-iteration`。
