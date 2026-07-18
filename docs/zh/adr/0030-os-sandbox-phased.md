# ADR-0030 · OS 级执行沙箱分阶段落地（唯一剩余 P0）

- 状态：**Proposed（2026-07-18·待用户拍板）**。本 ADR 只定方案与阶段切分，零代码改动；
  实现须逐阶段经用户 go（阶段一小刀可单独放行，阶段二先跑兼容性 spike 再决定投入）。
- 关联：[[0020]] env 擦洗（本案的纵深防御前作）· [[0025]] ShellGuard 复合命令分解 ·
  完成度重审计 `reports/completion-reaudit-20260718.md` §3 第 1 条（残余债之首）·
  S77 审计 P0① · 记忆 `beta-safe-redteam-posture`（13 外泄向量活体探针·本案验收复用）·
  记忆 `product-positioning-internal-engine`（内部发动机定位=本案按加固项排期而非商用否决级）·
  记忆 `cubesandbox-cloud-sandbox-candidate`（云路线候选·阶段三）
- 授权边界：AGENTS §3 triage 锁将 sandbox rollout 列为 KEEP_PLACEHOLDER「别扩展」——
  **本 ADR 是计划文档，不触锁**；任何实现开工前须用户批准本案（批准即更新锁表）。

## 背景与威胁模型

**现状三层防御与它们各自承认的极限**（2026-07-18 逐条核实·非文档转述）：

1. **静态扫描**（`shell_guard.py`）：段 leader + 深度正则 + wrapper/替换提取 + 秘密路径门 +
   网络出口门。质量已远超 S77 时的字符串黑名单，但 `shell_guard.py:93-94` 与
   `env_sanitizer.py:1-13` **白纸黑字承认围不住解释器**——`python -c "urllib..."` 一行绕过。
2. **env 擦洗**（ADR-0020·`command_tools._env()`）：子进程拿不到模型凭证。收窄了外泄标的，
   但磁盘上的 `.env`/密钥文件对子进程仍可读（秘密路径门只拦**命令文本里点名**的路径）。
3. **beta_safe 档**（1.2.63 红队）：shell 整关=密不透风，但 opt-in、默认不启用。

**执行咽喉是单点**：模型 shell 全部经 `command_tools.py:35` 的
`subprocess.run(shell=True, cwd=context.root, env=sanitize(...)`——与 S87/S88 同款
「守卫放在唯一的门上」的形状已经具备，本案只需换门框，不需要追写路径。

**威胁模型（写死，防 scope 漂移）**：防的是**模型生成的命令**四件事——
①网络外传（数据/代码出网）②工作区外写/删 ③读取工作区外敏感文件（浏览器凭证、ssh key、
别的项目）④持久驻留（daemon/计划任务逃出 run 生命周期）。
**不防**：恶意用户（用户是信任方）、harness 自身被攻破（Python 主进程是 TCB）、多租户隔离
（内部单人定位·见记忆）。**同名警告**：`sandbox_backend.py` 是候选工作区的**写隔离**
（worktree/复制），不是进程沙箱——G12 的 `TaskGraphScheduler` 同名不同物教训，先点破。

## 主流锚点（T11·为什么默认形态是「断网+限写」）

Codex 云任务 agent 阶段默认断网、Cursor Seatbelt 沙箱默认无网、Copilot 防火墙默认开+allowlist。
收敛结论：主流的沙箱默认不是「更聪明的扫描」，是**网络默认关 + 文件系统默认只有工作区可写**，
放行走显式 allowlist。我们的 `allow_network`/`allow_shell` 政策位已存在，缺的是**执法机制**——
今天它们的执法是静态扫描（可绕），不是 OS。

## 分阶段方案

### 阶段一 S-A「进程围栏」——Job Object + 会话隔离（天级·可独立放行）

把 `command_tools.py:35` 的 spawn 包进 **Windows Job Object**（POSIX 对应 `setsid`+rlimits）：

- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`：run 结束/超时/被 Stop ⇒ 整棵进程树必死，
  **关掉威胁④（持久驻留）**——今天 `timeout` 只杀直接子进程，`start /b`、后台 `&`、
  detached 进程全部逃生。
- `ActiveProcessLimit` + `ProcessMemoryLimit`：fork 炸弹/内存炸弹从「机器卡死」降为「命令失败」。
- 实现面：ctypes（CreateJobObject/SetInformationJobObject/AssignProcessToJobObject），
  stdlib 零新依赖，与 S88 的锁同一工艺水位；子进程需 `CREATE_SUSPENDED` 起、入 Job 再放行，
  防窗口期逃逸。
- **诚实边界**：不管网络、不管文件写。它是围栏不是沙箱——但它把「run 结束=干净」这个
  用户直觉第一次变成 OS 保证。
- 验收：探针=命令里 spawn detached 子进程 → run 结束后 OS 查无存活；fork 炸弹 → 命令失败
  而非机器失去响应；既有 shell 测试零回归。

### 阶段二 S-B「默认关网+限写」——AppContainer（周级·先 spike 再定投入）

用 **AppContainer**（Windows 10/11 内置，零安装依赖）承载模型 shell：

- **网络**：AppContainer 无 `internetClient` capability ⇒ WFP 层出站全断——
  `python -c urllib` 在 socket 层失败，**扫描围不住的那类威胁①在 OS 层关死**。
  `allow_network=true` 的档才授予 capability（政策位从「建议」变「执法」）。
- **文件**：AppContainer SID 默认几乎无处可写；对 workspace root + run 专属 TEMP 显式授
  ACL ⇒ 威胁②③收敛为「工作区+temp 可写、系统与他处只读或不可见」。
- **风险=兼容性，不是原理**（这就是 6-12 周估算的主体）：git/pytest/npm/uv 在 AppContainer
  内跑真实仓库会撞什么（用户 profile 路径、console handle、命名管道、antivirus 交互）
  ——**没有真 spike 数据前不许拍投入**。故本阶段拆两刀：
  - **S-B-spike（~2-3 天）**：一个探针脚本在 AppContainer 里对本仓库跑
    `git status / pytest -q 单测子集 / npm --version / ruff check 单文件`，产出兼容矩阵
    + 每工具的 ACL/capability 需求清单。**spike 结果决定 S-B 是「照做」「带 allowlist 豁免做」
    还是「换 WSL2 路线」**——用证据拍，不硬想（[[keep-docs-aligned-no-drift]]）。
  - **S-B-impl**：按 spike 结论接进咽喉 + 档位绑定 + 红队复跑。
- **否决的替代路线（记录理由防止兜圈）**：
  - Windows Sandbox：每命令一台 VM，秒级冷启+无持久工作区，与「发动机」节奏不容。
  - WSL2/Docker：真实仓库在 `/mnt/` 跨文件系统 IO 慢一个量级 + 要求用户装组件/许可证
    （Docker Desktop）——作 S-B 的 fallback 而非首选。
  - runas /trustlevel、纯 Restricted Token：只降权不断网，防不住①，单独做收益不够。
- 验收：**1.2.63 的 13 条网络外泄向量活体探针整套复跑**——今天它们靠 denylist+env 擦洗
  挡住，S-B 后必须在 **socket 层**死掉（含解释器 payload）；兼容矩阵里列明的工具在沙箱内
  真跑通过；`allow_network` 两态各探一遍。

### 阶段三 S-C「云执行」——CubeSandbox/E2B 兼容（推迟·随 B3）

Linux/KVM 级隔离，天花板最高，但绑定 CloudSessionExecutor（现为诚实 stub）与网络依赖，
且触「真 cloud VM background」冻结项。**本 ADR 不解冻它**，只登记：S-B 若 spike 失败，
云路线是备胎之一；启动须另行 DecisionPoint。

## 档位绑定（与既有权限模型对齐·不新造开关）

| 档位 | 今天 | S-A 后 | S-B 后 |
| --- | --- | --- | --- |
| beta_safe | shell 整关 | 不变 | 不变（仍是最硬档） |
| ask_everything | 逐条人审 | +围栏 | +沙箱（人审不变） |
| reviewed_auto / auto | 扫描+env 擦洗 | +围栏 | **+断网限写沙箱默认开**；`allow_network=true` 显式放行出网 |

高危 shell/deploy/push 的常开硬 guard 不随本案放松（AGENTS §5 不变）。

## 决策请求（三个都可独立拍）

1. **S-A 放行**：天级小刀、stdlib 零依赖、单咽喉改动、既有测试作回归网——建议直接 go。
2. **S-B-spike 放行**：~2-3 天纯探针（不动生产码），产出兼容矩阵后**再回来拍 S-B-impl**。
3. S-C 维持冻结，仅作 S-B 失败时的备选登记。

## 不做清单

多租户隔离、防恶意用户、harness 自身沙箱化、kernel 级监控、跨机隔离——均超出威胁模型；
「更强的静态扫描」也不做（1.2.63 已证边际收益归零，钱要花在 OS 执法上）。
