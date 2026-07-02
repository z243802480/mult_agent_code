# S75 — Beta 安全前置（access profile）+ review/repair 门控诚实化 · Signoff

- 日期：2026-07-02
- ACTIVE_PHASE：Post-S73 Beta convergence · ACTIVE_SLICE：S75（承接 S74）
- 用户指令（逐字）：「按照你的建议进行吧。2 条都可以做。但功能是否做要依据调研情况。非主流产品化做法的技术实现或者功能我们也就可以放弃掉。如果非常有利于完成需求，我们就需要实现，如果文档不合理的可以更新文档。」
- 两条方向（承接 S74 收尾提出的高杠杆项）：① 外部 Beta 安全前置；② 解锁一个 DO_NOT_TOUCH DecisionPoint（真接 /run review 门 / repair 预算 gate）。

## 1. 方法：3 路并行侦察（调研先于实现）

用户明确「功能做不做依据调研」，故先派 3 代理并行：

- **内部 recon A（shell/policy 层）**：硬闸门在 `security/shell_guard.py:176`（`permissions.get("allow_shell")`）**非** execute_command；`load_policy_config` 是唯一装载入口；已有可复用命名档模式 `active_budget_profile`+`budget_profiles`；`研发总计划 1.2.7-1.2.8` 已把「Beta 放量前 shell 收窄/关闭」列为前置。**结论：策略层关 shell 全锁外可做。**
- **内部 recon B（run/review/repair）**：`/run` 只读既存 `eval_report`（`run_command.py:1764`），不触发 review；`record_repair_attempt`（`budget.py:185`）**确证零生产调用者**（grep 仅定义处，审计属实非误报）；真接线均须动 DO_NOT_TOUCH。
- **外部调研 C（主流做法）**：WebSearch Codex CLI（sandbox `read-only`/`workspace-write`/`danger-full-access` + approval `on-request`；`on-failure` 智能策略已弃用）、Claude Code（permission modes + hook/Stop 触发验证 + `stop_hook_active` 防死循环）、OpenCode（per-tool allow/ask/deny）、Aider（auto-lint 默认开、auto-test opt-in）。

**关键收获**：调研把 ② 从「解锁去接 ledger/wrapper」纠正为「大部分是该弃的过度设计 + 文档不实，真正主流的只有内联验证一件」。

## 2. 判定表（严格按用户判据：主流+利需求→做；非主流→弃；文档不合理→改；撞锁→DecisionPoint）

| 项 | 调研结论 | 决定 | 边界 |
|---|---|---|---|
| ① 命名受限执行档（默认关 shell/network，可显式升级） | 主流（≈Codex `read-only`、Claude `default`/`dontAsk`）；North Star 已承诺前置 | **做** | 全锁外 |
| ② repair 预算 ledger（`record_repair_attempt`/`max_repair_attempts_total`） | 正是要避开的过度设计（Codex 弃 `on-failure`；市场只用简单计数） | **弃接线** | 改文档 + budget.py 注释 |
| ② 新 run-then-review 包装命令 | 主流是内联；第二条 run 路径反直觉 | **弃** | — |
| ② /run 内联验证真门 | 主流形态；但 Claude Code 亦用 hook 而非硬编核心循环，且现有 review/accept+nudge 已达同效 | **DecisionPoint，建议缓** | 真做须动 `run_command.py`（DO_NOT_TOUCH） |

## 3. ① 落地（全锁外，mainstream-minimal）

- 新建 `src/asteria_runtime/core/access_profile.py`：`BUILTIN_ACCESS_PROFILES.beta_safe`（档定义在代码=单一真源，避开已占用的 `execution_profile`/`permission_mode` 命名），`apply_access_profile`（active 时覆盖 permissions，null/未知=no-op 行为不变）、`available_access_profiles`（用户 `access_profiles` 覆盖内置）、`access_profile_summary`（doctor 用）。
- `core/policy_config.py`：`load_policy_config` 两条返回路径均 `apply_access_profile(...)`；磁盘只留开关，基础权限不被静默改写。
- `templates/policies.default.json`：加 `active_access_profile: null`。
- schema 双份（`schemas/` + `src/asteria_runtime/schemas/`）：加可选 `active_access_profile`（string|null）+ `access_profiles`（object）。
- `commands/doctor_command.py`：`_access_profile_summary()`（读原始 policies.json → merge_defaults → apply → summary，**只读无副作用**）+ 顶部 `Access profile:` 文本行 + 结构化 `access_profile` 字段（加入 stable_fields，doc_contracts 示例 `doctor_control_surface.json` 与 gate 内嵌 doctor stage `gate_control_surface.json` 同步）。

**验证**：
- 红队测试 `test_beta_safe_access_profile_hard_disables_shell_and_network`：beta_safe 下 `permissions.allow_shell/allow_network` 均 False，且 ShellGuard 真拒 `ls -la`/`python --version`/`curl ...`。
- 解析测试 `test_apply_access_profile_beta_safe_overlays_permissions` + `test_load_policy_config_resolves_access_profile_without_rewriting_switch`（消费者见受限态、磁盘留开关）。
- CLI live 冒烟：`init` → doctor `none (shell on, network off)` → 设 `active_access_profile:beta_safe` → doctor `beta_safe (shell off, network off)`。

## 4. ② 落地（诚实化 + 弃）

- **repair**：`budget.py:record_repair_attempt` 加注释「有意不接线，effective 上界=run_command 派生 cycle 上限+no-progress，对齐主流 max-turns/block 计数；跨 run ledger 刻意不采用」；`docs/zh/质量与评估.md §7` 措辞由「待 DecisionPoint 补」改「有意不采用过度设计」。
- **review**：`docs/zh/运行命令.md` 流程图删误导的内联 `-> review`，改显式 `review`/`accept` 步 + 诚实旁注（Claude Code 亦用 hook 触发验证，现有显式验证+Studio `runVerificationHint` 已是主流形态，真内联须解锁 `run_command.py` 列 DecisionPoint）。
- **wrapper**：弃（非主流第二 run 路径）。

## 5. 全量验证

`pytest tests/unit -q` **907 passed**（904→907，+3：红队/解析×2）；`ruff check` clean；`doc_contracts` 22；CLI live 冒烟通过。**未触碰** execute_command / run_command / gate_status / acceptance·real_model 栈。

## 6. 残留 DecisionPoint / 后续

- **/run 内联 review**（须解锁 `run_command.py`）：建议缓——现有 `review`/`accept`+`runVerificationHint` 已达主流同效，Claude Code 本身也不把验证硬编进核心循环。等用户明确要「/run 自身自动验证」再解锁。
- **外部 Beta 邀请**：安全前置机制已交付（beta_safe pin + doctor 核实 + 红队测试），剩「真实规模下对关停态再跑一轮红队 + 用户拍板发邀请」；属用户本人操作。
- **未做（诚实边界）**：access 档是策略层闸门非内核 sandbox；对不可信输入的彻底隔离仍需 sandbox（KEEP_PLACEHOLDER），beta_safe 是 sandbox 落地前把攻击面降到最低的主流做法。

遵守 [[keep-docs-aligned-no-drift]]、[[convergence-direction]]、[[truly-complete-system-goal]]。
