# 低负担 set-and-forget 缺口地图(2026-07-13)

**目标**:让系统像 Claude Code / Codex / OpenCode 一样——**一次设好权限 → 自动开发连跑 → 只在计划 + 高危打断**。
不是更丰富的驾驶舱 / 更多证据展现(那是加负担·反模式,见记忆 `low-burden-set-and-forget-ux`)。

方法:两只只读代理实测后端(`src/asteria_runtime/`)+ Studio(`studio/`)真实负担面,以 CC/Codex/OpenCode 打断模型为基准。**未改任何文件。**

## 一次 run 操作者被迫做的事(零配置默认 `reviewed_auto` / 三环全关)

| 步 | 动作 | 负担性质 |
| --- | --- | --- |
| 1 | `asteria run "goal"` → 自动 init/research/plan/execute·规划期 0 打断 | ✅ 已达标(计划自动进,`plan` 显式审查是 opt-in) |
| 2 | **任一 task 失败 → run 停在"可 resume 会话边界"→ 你得手敲 `resume`/`debug`/`replan`** | ❌ **头号负担**·CC/Codex 会自动 repair |
| 3 | **`asteria accept` 收尾**(改动早落盘了)→ 跑 review·结算晋升·翻 completed | ❌ 多余仪式·竞品改完即完 |
| 4 | 情形性 `asteria decide`:高危 shell / 中高危 runtime request / 预算门 | 高危合法·中危偏 friction |

→ **一个带一次失败的任务 ≈ 2 次强制人工触碰(resume + accept)**,CC/Codex ≈ 0。

## 缺口(按产能杠杆排序)

### #1 自主环默认关 → 每次失败 stop-and-ask【最大杠杆·后端·✅ 已修 2026-07-13·§16 v1.2.27】
- 三环全默认 `false`:`auto_repair`(`policies.default.json:143`)、`auto_replan`/`auto_replan_goal`(键缺失=falsy·`execute_command.py:440`/`run_command.py:1499`)。
- 环关时 task `blocked` → `run_command.py:1330` 跳过 goal-replan → 落 `:1336-1366` 停在 resumable boundary、报 needs_attention、等人 `resume`。
- 脊梁**任务内**工具/命令失败仍会作 observation 回灌自纠(`max_rounds+4` 保险丝)——所以自纠得了的失败不 block;但模型放弃/真 blocked 时=环关=停下问人。
- **修向**:出厂 `reviewed_auto`/`auto` 档**即代表"设一次就自动开发"**——选这两档时三环默认开(预算/recovery-cycle/lineage-cap 保险丝原样保留作兜底)。**这是自主性 DecisionPoint,须用户拍板**(承 `freeze-lifted-autonomous-loop`:环已造好·冻结解除·就差翻默认这一下)。**这一刀直接消掉步 2 的强制 resume,是"设权限→自动进行"真正兑现的关键。**

### #2 accept 收尾仪式【高杠杆·后端·✅ 已修 2026-07-13·§16 v1.2.28·知情推翻 v1.2.15 DecisionPoint】
- 直接写是默认(`execute_command.py:739`)、晋升默认自动批(`promotion.manual_approval_default:false`)——都已达标;**但 `accept` 是独立强制命令**(`accept_command.py:122-215`:跑 review·结算·翻 completed),不跑 run 停在未 finalize。
- Studio 侧把「标记完成」摆成持久"下一步"诱导多点一下(`RuntimeSnapshot.tsx:311-330`),而改动早落盘(`:261-265`)。
- **修向**:`auto`/`reviewed_auto` 下 review 干净即**自动 accept**;Studio「完成」变被动状态不是必点按钮。

### #3 命令审批 → 核实后=非负担缺口(2026-07-13)【已核实·结论翻转】
**核实结论**:逐命令暂停是 **denylist 驱动、与权限档无关**——`runtime_policy.create_policy_decision_if_needed:105` 只在 `shell_denial` 命中(破坏性/联网/密钥/发布)时暂停,普通命令(pytest/git status/echo)`shell_denial=None`→continue→**任何档都不暂停**(真栈 smoke 实证)。
- **无缺 allowlist**:后端**已是 CC 模型**(denylist deny 危险·allow 其余);ADR-0025 已修管道一刀切误挡。
- **BFF 只 `ask_everything` 前置弹**(`legacyPermission`:reviewed_auto/auto→"allow"→`server.mjs:487` 不弹)。
- **唯一真问题=一行前端文案 overclaim**:`permissionTiers.ts` reviewed_auto 文案"命令…仍会为你暂停"暗示所有命令暂停(实际只危险命令暂停·同其它档);`auto` 档文案已准确。**属前端会话地盘·勿撞**——留给前端会话做一行诚实化,后端无需动。
- **不做**:后端命令 allowlist(无 friction 证据·危险命令本就该暂停·加=违收敛)。

### #4 内部质量门 block run【中低杠杆·后端】
- delegation-brief 门(`execute_command.py:604`)——**委派模式误挡本会话已修**(§16 v1.2.26);中/高危 runtime request 仍 block(`runtime_policy.py:348-379`),中危偏 friction。
- **修向**:审哪些内部门是"停下问人"vs"warn 继续"(计划质量门已是默认非阻断+静默自修·是好样板)。

### #5 运行中注意力税【低杠杆·纯前端会话地盘·勿撞】
- 完成后线程已很安静(ADR-0021 白名单·`ConversationTurn.tsx:148-162`);**运行中**仍有持久工具卡 + 底部多控件(next-action bar / suggested chips / issue-nav / jump-to-latest 并存)+ 完成后工具卡不消。
- **修向**(前端会话做):运行中主区收敛成安静 loop 进度·砍完成后残留工具卡·底部单一权威"下一步"。

## 关键洞察(交付给用户)

1. **产能最大杠杆在后端自主环默认(#1),不在前端装修。** 前端权限**设置**已达 CC/Codex 水准(一次前置选档);缺的是**选了档它却不真自动**(环关→照停问人)。
2. **#1/#2/#4 是后端(我的地盘·不撞前端会话);#5 是前端会话地盘;#3 分裂需先核实。**
3. **#1 是自主性 DecisionPoint**——翻环默认=把"监督态"变"设一次自动开发态",须用户显式授权(逐档:`auto`=全自动开环·`reviewed_auto`=开环但高危仍问·`ask_everything`=保持逐步)。

## 第一刀 ✅ 已落地(2026-07-13·§16 v1.2.27)
把权限档与自主环**绑定成预设**:`auto`/`reviewed_auto` → 三环默认开(保险丝原样兜底),消掉强制 `resume`;`ask_everything` 保持现状。逐字节可回退(仍是 flag·只是默认随档走)。用户已拍板「绑定预设」并落地:`permission_policy.autonomy_rings_default_on` + 三处判定随档 + 删模板 `auto_repair:false`;1216 passed·brief `B-autonomy-rings-bind-permission-mode.md`。

## #2 ✅ 已落地(2026-07-13·§16 v1.2.28·正确性门自动收尾)
知情推翻 2026-07-02 "run 停 ready_for_review·不 auto-accept" DecisionPoint(命名测锁定)。auto/reviewed_auto 下干净 `completed` + 真测试退出码 pass(ADR-0018·**非模型 review**)+ 无 pending 风险 promotion → 自动翻 ACCEPTED,消掉 accept 点击 + 前端 nudge 从源头消失。未验证/失败/blocked/pending 风险留给人。ask_everything 保留显式 run→review→accept。brief `B-correctness-gated-auto-finalize.md`。

## 下一刀候选(承本图)
- **#3 命令审批 allowlist / 文案核实**(需先查 `lib/permission-level.mjs` + server 审批路径):前端说"哪档都暂停"vs 后端 auto 只挡硬门,定改文案还是加 CC 式命令 allowlist。
- **#5 运行中注意力税**(前端会话地盘·勿撞)。
