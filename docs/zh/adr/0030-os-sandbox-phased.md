# ADR-0030 · OS 级执行沙箱分阶段落地（**已收口·降级·2026-07-19**）

- 状态：**收口（2026-07-19·用户「收口吧·有一个轻量的就行·暂时对标主流·能稳定运行即可·以后上云在 cube 环境跑」）**。
  OS 沙箱**不再是 P0**——见文末「收口决定（2026-07-19）」段。轻量层已落地并保留：权限门（主安全层·对标主流）
  \+ S-A 进程围栏 + opt-in confinement；AppContainer 全工具兼容**不再追**；强隔离推迟到云 CubeSandbox（阶段三）。
- 历史状态：**Accepted（2026-07-18·用户「1+2 都做」授权 S-A + S-B-spike）**。
  - **S-A（进程围栏）已落地**：changelog 1.2.117·`core/process_fence.py`·Job Object KILL_ON_JOB_CLOSE +
    资源上限·4 单测含真 detached 孙进程被收掉 + 真栈探针零误伤 + 1362 pytest 零回归。
  - **S-B-spike 已跑（结论：隔离原理证实，路线清晰）**：见下方 S-B 段末「spike 结果」。
  - **S-B-impl / S-C 仍待用户拍板**（S-B-impl 的路线由 spike 结果收敛为「工具放置」问题·见下）。
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
- `ActiveProcessLimit=512` + `ProcessMemoryLimit=4GiB/进程`（**落地值·炸弹级阈值非精细配额**）。
- 实现面：ctypes（CreateJobObject/SetInformationJobObject/AssignProcessToJobObject），
  stdlib 零新依赖，与 S88 的锁同一工艺水位。
- **诚实边界**：不管网络、不管文件写。它是围栏不是沙箱——但它把「run 结束=干净」这个
  用户直觉第一次变成 OS 保证。
- **已落地（1.2.117）·实现纠一处 ADR 初稿的话**：本节初稿写「子进程需 `CREATE_SUSPENDED` 起、
  入 Job 再放行」——实现时选了 **Popen 后立即 assign**（不 suspend）：`subprocess.Popen` 不暴露
  子进程主线程 handle，拿不到就 ResumeThread 不了，手写 CreateProcess+管道捕获进核心路径的
  风险不划算。残留窗口=cmd.exe 加载/解析/CreateProcess 目标之间的微秒级，且默认 job 禁
  breakaway ⇒ 逃逸要求攻击者显式带 breakaway flag（模型普通命令不会）——**如实记进 docstring，
  不假装零窗口**。
- 验收（已过）：真 detached 孙进程（`DETACHED_PROCESS` 每 50ms 写心跳）→ run 结束后心跳停增
  （被 KILL_ON_JOB_CLOSE 收掉）；git + 8 并发子进程零误伤；既有 shell 测试 318 零回归。

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

**★ spike 结果（2026-07-18·跑了·`scripts/spikes/appcontainer_probe.py` + `_result.json`）**：
真起 AppContainer（`STARTUPINFOEX` + `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`·无 capability）
对五个用例的实测，**5/5 期望达成、逃逸写入确认未落盘**——隔离原理证实：

| 用例 | 结果 | 结论 |
| --- | --- | --- |
| whoami /user（System32） | exit 0 | AppContainer 能起进程、容器身份成立 |
| curl http://example.com（无 capability） | **exit 28（超时）** | **无 internetClient ⇒ 出站在 OS/WFP 层死**——这正是 S-B 对威胁① 的承诺，`python -c urllib` 那类外泄够不着 socket |
| 写工作区内（已授 full ACL） | exit 0 | 授权工作区可写 |
| 写工作区外 `C:\Windows\…` | **exit 1 + 文件确认未落盘** | 工作区外写被 OS 拒（威胁②③） |
| 用户目录解释器（无 ACL 授权） | **exit 0xC0000022 = ACCESS_DENIED** | 用户 profile 里的 `python.exe` 无 ACL 授权时容器读不了、起不来 |

**路线由此收敛（不再是「照做/allowlist/WSL2」三选一的悬念）**：隔离**能用且默认就严**，唯一真工程
问题是**工具放置**——第一版 spike 试 `icacls /T` 递归授整个 `python313`（含 site-packages 数千文件）
**卡了几分钟**，这条路（per-container ACL 授用户 profile 解释器目录）**成本不可接受、判死**。
S-B-impl 的正解是二选一：**(a)** 把运行时工具（python/git/node）装进/软链到一个**一次性授
`ALL_APPLICATION_PACKAGES` 读执行**的固定位置（装机一次·非每 run）；**(b)** 只对 `workspace + 专属
TEMP` 授容器 ACL（小树·快·spike 已证 `grant_full` 秒级），工具靠 (a) 的固定位置读。**不需要 WSL2 fallback**
（隔离在原生 AppContainer 已成立）。**残余待测（S-B-impl 内做，非拦路）**：git/pytest/npm 在容器内跑
真实多进程仓库的兼容性（命名管道/console handle/AV 交互）——spike 已证机制层通，这些是接线细节。
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

## 决策请求（状态·2026-07-18 更新）

1. ~~**S-A 放行**~~ **✅ 已做（1.2.117）**：进程围栏落地、验收过。
2. ~~**S-B-spike 放行**~~ **✅ 已跑**：隔离原理证实（见上表），路线收敛为「工具放置」。
3. ~~**S-B-impl 待拍板**~~ **✅ 首刀落地（1.2.120·用户「按你建议继续」授权·opt-in 默认关）**：
   `sandbox_launch`（AppContainer+Job Object 叠加）+ `sandbox_provision`（profile+工具 ALL_APPLICATION_PACKAGES
   授权+workspace/io ACL）+ command_tools 咽喉接线（`permissions.sandbox_shell`·fail-closed）+
   `asteria sandbox status/provision` 命令。**核心机制真机证实**：默认无 capability ⇒ 网络出站 OS 层断
   （对联网本机实测·`python -c urllib` 解释器绕过也够不着 socket）+ 写限工作区（区外写被拒且未落盘）。
   **诚实剩余**（写进代码 docstring）：①`allow_network=true` 逃生口暂无效——**1.2.121 纠正了 1.2.120 的
   错误归因**：不是「capability 不进 token」（whoami /groups 本不显示 capability·方法弱），真相是本机出网走
   **loopback 代理**（AppContainer 默认拦 loopback·与 internetClient 无关），到代理需 loopback 豁免、直连
   互联网才需 internetClient+防火墙——依机器网络而定·fails closed 故安全；②工具 provision 是显式一次性慢操作
   （已移出热路径）③**默认 OFF 有据不是保守——1.2.122 工具链兼容性 spike 证「默认开不可行」**：AppContainer 里
   ✅python/stdlib/ruff 能跑，❌**git** / **pytest** / **node·npm** 均挂 ⇒ 要逐工具兼容性工作才谈默认开。
   **⚠️ 根因已由 1.2.13x「试修 spike」纠正+统一——见下方 S-B-fix 段**（1.2.122 把 git 归「msys /dev/null」、
   pytest 归「解释器真路径解析」是**两个错误归因**：pytest 的「real location」只是无害警告·realpath 实际成功；
   真因是 git 和 pytest **同一个**——容器内打不开 NUL 设备）。**另修 1.2.121：命令引号 bug 曾让 1.2.120 的网络
   证明假绿（命令没跑冒充网络被拦）·已修+回归护栏。**
4. **S-C（云）维持冻结**，spike 证明原生方案够用，云路线连备胎都用不上，仅登记。

### S-B-fix「试修 spike」结果（1.2.13x·用户「诊断-试修 spike 先行」授权·`scripts/spikes/sandbox_toolchain_fix_probe.py` + `_result.json`）

**统一根因（真机确认·纠正 1.2.122 的两个错误归因）**：git 和 pytest 挂在**同一件事**——AppContainer 内
**打不开 NUL 设备**。逐条证据：

| 实验 | 结果 | 结论 |
| --- | --- | --- |
| `git --version`（含 `HOME` 受控 + `GIT_CONFIG_NOSYSTEM`） | exit 128·`could not open '/dev/null' for reading **and writing**` | git 启动即以 RDWR 开 `/dev/null`·配置改不动它 |
| `python nul_modes.py`（脚本文件·避 `-c` 转义） | `RDONLY=FAIL(errno13) WRONLY=FAIL(errno13) RDWR=FAIL(errno13)` | **CRT 对 NUL 的 open 三模式全被拒（Permission denied）** |
| `cmd /c "echo hi>NUL"` / `type NUL` | exit 0 | **cmd 内建 NUL 重定向走的 CreateFile 路径被允许**——这就是 1.2.122 简单命令没暴露此坑、且早期 `echo>NUL` 误导的原因 |
| `python -m pytest -q`（完整 traceback） | exit 1·`_pytest/capture.py` FDCapture → `os.open(os.devnull, os.O_RDWR)` → `PermissionError: 'nul'` | **pytest 真因=开 devnull·不是「解释器真路径」**（后者 realpath 实测成功·只是启动警告=红鲱鱼） |
| `python -c realpath(sys.executable)` | exit 0·返回正确路径 | 坐实「real location」是无害警告 |
| `python -m pytest --capture=sys` | exit 3·另一处 INTERNALERROR | 关 FDCapture 只避开第一个 devnull open·**非干净绕法**（pytest 多处碰 nul） |

**⇒ 路线判据（给 S-B-impl 的证据结论）**：native AppContainer 默认开的**唯一真障碍已收敛为一件事**——让容器能开 NUL
设备。**impl 方向按证据排序**：**(1) 首选·研究给容器授 NUL 设备访问**——`\Device\Null` 的对象 DACL 是否可向
容器 profile SID / `ALL_APPLICATION_PACKAGES` 授（一次性 provision 步·若成立则 git+pytest **一并解**·杠杆最高）；
**(2) 若 NUL 设备授权不可行**：per-tool 绕法不够（pytest `--capture=sys` 已证只避开一处·git 无绕法）⇒ 这成为
**git/pytest 类工具走 WSL2/容器运行时 fallback**（ADR §阶段三推迟项）的证据·或接受沙箱默认开只覆盖不碰 NUL 的
负载。**node/npm 的乱码 exit 1 是独立项**（疑编码/console handle·本 spike 未深挖·记 backlog）。**明确不做**：本 spike
只取证据+纠正归因·未改任何生产码（1 探针脚本+1 结果 json+本 ADR 段+changelog）·NUL 设备授权的真实现是下一刀 impl。

### S-B-fix phase 2「NUL 授权可行性」真机验证（1.2.14x·用户「先证可行再 impl」授权·`sandbox_nul_grant_probe.py`（诊断）+ `sandbox_nul_grant_test.py`（授权测试·可逆）+ 各 `_result.json`）

**结论：NUL 设备 AAP 授权可行·完全修好 git·让 pytest 越过 NUL 墙（但 pytest 还有第二道同源墙）。全程可逆·真机实测。**

1. **先安全排除 namespace 假设**（phase 1·零系统改动）：容器内用三条路径开 NUL——`nul`（CRT→DOS 设备映射）/
   `\\.\NUL`（Win32 设备路径）/`\\?\GLOBALROOT\Device\Null`（对象管理器·**绕过** DOS 映射）——**三条全 errno13**。
   ⇒ **不是 DOS 设备映射缺失**，是设备对象层的访问控制。
2. **只读查 NUL 设备 DACL**（零改动）：`O:BA D:(A;;0x1201bf;;;WD)(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x1200a9;;;RC)`——
   **`WD`=Everyone 已被授读+写·世界都能开 NUL·容器却打不开**。⇒ **拦截不是没授权·是 AppContainer 语义不认
   「Everyone」ACE**：对 AppContainer token·设备对象 DACL 必须**显式**含 `ALL_APPLICATION_PACKAGES`(AC) ACE
   才放行（跟 provision 给工具目录授 AAP 同一个道理）。NUL 的 DACL 恰**无 AC ACE**。
3. **授权测试**（可逆·finally 恢复原 DACL·additive+benign）：给 NUL DACL 追加 `(A;;FA;;;AC)` → 容器内重测：

   | | before grant | after grant（+AC ACE）|
   | --- | --- | --- |
   | `os.open('nul', O_RDWR)` | FAIL(errno13) | **OK** |
   | `git --version` | exit 128（/dev/null）| **exit 0**（`git version 2.52.0.windows.1`）|
   | `python -m pytest -q` | exit 1（`os.open(os.devnull,O_RDWR)` PermissionError 'nul'）| **exit 2**（越过 NUL 墙·撞第二墙）|

   恢复后 DACL 逐字节回到原样。
4. **pytest 第二道墙（同源·已定位）**：加 AC 后 pytest 不再挂 devnull·改挂 collection——`os.stat('C:\Users\…\Temp')`
   → **WinError 5 拒绝访问**。根子是**同一个 AppContainer 语义**：容器 stat/遍历任何**未显式授 AAP 的目录**都被拒
   （Everyone 不算数·现在体现在**目录**上）·pytest 的 rootdir 发现**向上遍历祖先目录**撞到未授权祖先。**本 spike 里祖先
   是 Temp（因工作区建在 Temp 下·部分是 spike 产物）·生产里是工作区的祖先目录**。设 `TEMP`/`TMP` env 不解（祖先来自
   工作区路径而非 env）。

**⇒ 给 S-B-impl 的判据（已从「三选一悬念」收敛到明确工序）**：
- **git**：NUL 设备授一条 AC ACE 即完全解——这是 **provision 层一次性操作**（`SetSecurityInfo` 加 AC ace·**非持久：
  内核每次 boot 重建 `\Device\Null` 用默认 DACL·无 AC** ⇒ provision 须每 boot/每 provision 重加·记进设计）。
- **pytest**：NUL 授权 + 解决**祖先目录遍历**——两条候选（impl 再定）：**(a)** 给容器授工作区**祖先链**的 AAP 遍历（X）
  权（小心别过度放大暴露面）；**(b)** 给 pytest 注入 `--rootdir=<ws>`/`confcutdir` 边界让它别向上走（run_tests 工具规范化·
  但改的是模型命令·须权衡）。
- **风险/边界（诚实）**：NUL 授 AC 是系统设备 DACL 改动·但 **additive+benign**（NUL 是位桶·Everyone 本就可读写·授
  容器无新增安全暴露）且**非持久**（boot 自愈）；祖先遍历授权要**收窄到工作区链**别顺手放大。**明确不做**：本 phase 仍
  只取证据·未改任何生产码（2 探针脚本+2 结果 json+本段+changelog）·真 provision 接线是下一刀 impl。

### S-B-impl git 半边落地（1.2.141·用户「做 S-B-impl 的 git 半边」授权）——NUL 授权接进 provision + 一处 overclaim 纠正

**已落地（生产码）**：`sandbox_provision.ensure_nul_device_access()`——幂等给 NUL 设备加 AC ACE（先只读查 DACL·
已有 AC 则跳过·否则 `SetSecurityInfo` 追加），**per-process 缓存**（`_nul_access_ensured`·因 boot 非持久·进程内保证
一次即可·重启后新进程自动重加）·**best-effort 不 fail-close**（授不了只退回 git/pytest 各自失败·不砸整个沙箱的
网络/写围栏——NUL 是位桶非安全边界）。接进 `ensure_sandbox`（每 fresh 进程自动保证）+ `provision_toolchain`（运营者
`asteria sandbox provision` 一并预热并报状态）。3 单测（DACL 幂等检查三态/非 Windows no-op/进程缓存短路）+ **真机集成
测试 `git --version` 经生产 `ensure_sandbox` 路径 exit 0**·mypy_ratchet(78)/ruff 净。

**⚠️ 纠正 phase-2 的一处 overclaim（诚实）**：phase-2 表格写「git `--version` exit 0 ⇒ **完全修好 git**」——**不准确**。
真机复验：NUL 授权后 `git --version`（不碰 cwd）✅ exit 0，但 **`git status`/`git add` 仍 exit 128**（`fatal: Unable to
read current working directory: Permission denied`）——**git 仓库操作要解析 cwd 完整路径·同样撞祖先遍历墙**（与 pytest
第二墙同源）。**⇒ 「git 半边」实际分解为 (1) NUL 授权【本刀已落·`git --version` 类通】+ (2) 祖先遍历【与 pytest 共享·
git 还需更多·下一刀】。** 诊断补充（真机·`_diag_ancestor` 探针·已删）：给容器授工作区祖先链 RX 遍历后 **pytest exit 0**
（祖先遍历修好 pytest），但 **git status 仍失败**（git 读 cwd 要的不止 stat 祖先）·且 **icacls 授 Temp/用户 profile 这类
大祖先目录会 30s 超时**（生产工作区祖先通常小·此为 spike 工作区建 Temp 下的产物）。**下一刀 impl**：祖先遍历授权
（收窄工作区链）+ 查清 git 读 cwd 还缺什么·完成后 git 仓库操作 + pytest 一并通。

### S-B git 半边·祖先遍历方案证伪（1.2.14x·用户「实现祖先遍历授权·直接 API」授权 → **真机跑出负面结果·方案作废**）

**结论：祖先遍历授权对 git 是死路——既不修 git、又慢到不可用。改回决策。** 真机验证（直接 API `SetEntriesInAcl`+
`SetNamedSecurityInfo` 给工作区祖先链含盘根加 profile-SID traverse-only(X) ACE·比 icacls 更底层）：
- **git status 授全部祖先后仍 exit 128**（`Unable to read current working directory`）——**祖先遍历授权不修 git**。
  真因更深：git-for-windows 的 `mingw_getcwd` 用 `CreateFileW(cwd, access=0, FILE_FLAG_BACKUP_SEMANTICS)` +
  `GetFinalPathNameByHandle` 拿 cwd 规范全路径·容器里这条链失败·非「授祖先 traverse」能解（授了照挂）。
- **且慢到不可用**：直接 API 授 6 个祖先耗时 **145s**（不是 icacls 特有的慢·是 `SetNamedSecurityInfo` 对
  Temp/user-profile 这类大目录本身慢·疑触发子项继承重算）——热路径根本用不起。
- **副作用已如实清理**：spike 在 `C:\`/`C:\Users`/`…AppData\Local\Temp` 等 6 个系统目录留下的 traverse ACE·
  已用直接 API `REVOKE_ACCESS` 逐个移除并**逐目录 icacls 复查=0 残留**·系统恢复原样。危险 spike 脚本（改系统 ACL·
  清理不可靠）已删·不留可运行残留。
- **⇒ 重新判据**：**pytest 在 native AppContainer 已能跑（NUL 授权就够·harness 自验工具通=默认开的大头）；git 仓库
  操作是 native AppContainer 的原生限制·祖先授权解不了。** 剩余真实选项：**(A) 标默认开·git 仓库操作列已知限制**
  （网络/写围栏+pytest 已成立·git push 本就常开硬 guard）；**(B) git 走 WSL2/容器运行时 fallback**（阶段三推迟项·
  独立一条线）。**不再走祖先授权**（本段证伪）。**明确不做**：`ensure_sandbox` 未加任何祖先授权（证伪故未接线·生产码
  只有 1.2.141 的 NUL 授权）·git 半边的后续走向待用户在 (A)/(B) 间定。

## 收口决定（2026-07-19·用户「收口·轻量对标主流·稳定运行即可·强隔离以后上云」）

**触发**：用户质疑整条 OS 沙箱 P0 的前提——「其他软件都怎么做的？我感觉它们没这个问题啊，都是用开发者自己的
环境吧」。逐条核实主流本地编码 agent 的执行安全姿态（置信度标注·非记忆断言即需查证）：

| 工具 | 本地默认做法 | 置信 |
| --- | --- | --- |
| Claude Code / Cursor / Aider | 跑在**开发者自己的环境** + 权限门（ask/allowlist/denylist）。OS 沙箱是**后加可选项**（CC：mac Seatbelt / Linux bubblewrap），默认不开 | 高 |
| OpenAI Codex CLI | **唯一**默认做本地 OS 沙箱——但用 **mac Seatbelt / Linux landlock+seccomp**，**不是 Windows AppContainer** | 高 |
| Devin / 云 agent | 隔离靠**远程 VM/容器**·非本地沙箱 | 高 |
| 任何工具用 Windows AppContainer | 查无 | 中高 |

**⇒ 纠正本 ADR「主流锚点」段的一处混淆（诚实）**：38–43 行把「主流沙箱默认=断网+限写」当成主流的**本地默认形态**——
不准确。那是这些工具的**云任务/沙箱模式**的默认；它们的**本地默认**是「开发者环境 + 权限门」。也就是说：**做本地
OS 沙箱的只有 Codex 一家·且用 mac/Linux 原语·主流没人走 Windows AppContainer 这条路。** 我们跟 git/pytest/NUL/
祖先遍历死磕的一路摩擦，本质是**选了主流不走的路自找的**（AppContainer 对 msys/git 的 cwd 规范化天然不友好）。

**决定**：
1. **OS 沙箱降级·不再是 P0**。理由：①主流本地不做 OS 沙箱·做的是权限门 ②权限门我们**早就有**（ShellGuard
   段 leader 分解 + 深度正则 + 秘密路径门 + 网络出口门·env 擦洗·beta_safe 密不透风档·shell/deploy/push 常开硬
   guard·跨 run 锁）——这一层已对标主流 ③AppContainer 全兼容是主流没验证过的路·投入产出比差。
2. **保留的「轻量层」（已落地·即产品的稳定安全姿态）**：**权限门=主安全层**（对标 Claude Code/Cursor/Aider 的
   本地默认）+ **S-A 进程围栏**（1.2.117·Job Object·run 结束=进程树必死·这是纯增益无摩擦）+ **S-B confinement 作为
   opt-in**（`permissions.sandbox_shell`·网络断+写限工作区·1.2.120 已真机证·给偏执负载用·不默认开）。
3. **AppContainer 全工具兼容不再追**：git 仓库操作（status/add）是 native AppContainer 的**已知原生限制**（`mingw_getcwd`
   的 cwd 规范化在容器里失败·祖先授权已证伪·见上段）；pytest 靠 NUL 授权（1.2.141）已能跑但不作为默认开的理由。
   **不再投入 AppContainer 兼容性工作**（allow_network 防火墙注册、大仓库广验、档位默认开全部**搁置**·非取消·云路线
   落地前无收益）。
4. **强隔离推给云 CubeSandbox（阶段三·维持推迟）**：真要 Linux/KVM 级隔离，等上云了在 cube 环境专门跑（记忆
   [[cubesandbox-cloud-sandbox-candidate]]）·不在本地手搓。启动仍须另行 DecisionPoint。

**保留不删的资产**（沉没成本转为可选能力·非废弃）：`sandbox_launch.py` / `sandbox_provision.py`（含
`ensure_nul_device_access`）/ `process_fence.py` / `command_tools` 的 `sandbox_shell` 咽喉接线 + `asteria sandbox
status/provision` 命令——都留着·S-A 围栏默认生效·confinement 走 opt-in·NUL 授权在 provision 时机会性执行。
**三个 spike 脚本**（`sandbox_toolchain_fix_probe`/`sandbox_nul_grant_probe`/`sandbox_nul_grant_test`）留作证据档。

**这不是失败收场·是威胁模型对齐**：本案真正兑现的是——把「run 结束=干净」变成 OS 保证（S-A）、把网络/写围栏证到
可用（S-B confinement opt-in）、把主流其实怎么做查清并纠正了本 ADR 自己的锚点混淆。AppContainer 全兼容这个**过度目标**
被主流现实和真机负面结果一起证否，及时止损。

## 不做清单

多租户隔离、防恶意用户、harness 自身沙箱化、kernel 级监控、跨机隔离——均超出威胁模型；
「更强的静态扫描」也不做（1.2.63 已证边际收益归零，钱要花在 OS 执法上）。
