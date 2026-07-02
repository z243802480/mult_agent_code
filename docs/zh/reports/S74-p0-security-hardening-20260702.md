# S74 P0 安全止血落地（2026-07-02）

> 承接 `S74-full-system-claims-audit-20260702.md` §3 的 P0。审计确认的 3 条 critical + 若干 high
> 安全裂缝：shell 工具绕过 PathGuard 读 secret、绕过 allow_network 外传、破坏性拦截被浅词表绕过、
> `.asteria/` 可写自提权、runtime_request 裸写毒化 schema。均在非 DO_NOT_TOUCH 的 security/tools/
> storage 层修复,未触碰 execute_command/run_command/gate 栈。

## 修了什么

### P0-1 shell 读 secret（critical/broken → 堵住）
`ShellGuard` 现接收 `protected_paths`（`command_tools`/`runtime_policy` 都已传入 workspace 策略值）。
执行前扫描命令里的 path-like token,命中 `.env`/`.env.*`/`secrets/`/`*.pem`/`*.key`/`id_rsa`/
`id_ed25519`/`.asteria/`（`.git/` 有意排除,避免误伤 git porcelain）即 `ShellPolicyError`,除非
`allow_secret_file_read=true`。输出重定向目标也过同一检查（防 `echo x > .env` 篡改）。
- 证据: `security/shell_guard.py` `_referenced_secret/_matches_secret/_path_tokens`；`tools/command_tools.py:28-31`；`core/runtime_policy.py:145`。

### P0-2 shell 网络外传（critical/broken → 堵住）
`allow_network=false`（默认）时,按 segment leader 拦截 curl/wget/nc/ncat/netcat/telnet/ssh/sftp/
ftp/tftp/socat/iwr/Invoke-WebRequest/Invoke-RestMethod,以及 `git clone|fetch|pull|ls-remote`、
`pip download`。leader 检测走 quote-aware 分词,commit message 里出现 `curl` 之类不会误杀。
- 证据: `_network_hit` + `_segment_leaders`。

### P0-3 破坏性拦截绕过（high/partial → 堵住）
- 新增 leader 级破坏工具: shred/truncate/dd/mkfs/sdelete/cipher/wipefs/blkdiscard。
- 新增全文正则（命中 flag/payload/引号内）: `find … -delete`、`find … -exec rm|del|unlink|shred|rmdir`、
  `shutil.rmtree`、`os.remove|unlink|rmdir`、`rmtree(`、`.unlink(`、`remove-item`、`rmdir`。
  —— 修复原 `_command_words` 剥引号导致 `powershell -c "Remove-Item …"` 漏网。
- 证据: `DESTRUCTIVE_LEADERS` + `DESTRUCTIVE_PATTERNS`。

### P0-4 `.asteria/` 自提权（medium → 堵住）
默认 `protected_paths` 增加 `.asteria/`（`templates/policies.default.json` + `init_command.py`）。
candidate workspace 在 `EXCLUDED_NAMES` 里不含 `.asteria`,内部 runtime 走 JsonStore（不过 PathGuard）,
promotion 用独立 `PathGuard([])`——故此项只挡住模型 file 工具/shell 改自身策略,不影响核心流。

### P0-5 runtime_request 毒化（high/broken → 堵住）
- packaged `src/asteria_runtime/schemas/runtime_request.schema.json` 的 status enum 补 `auto_applied`,
  与 repo-root 对齐（装成 wheel 后一次 auto-apply 不再毒化 jsonl 让后续 resume/compact/validation 崩）。
- 该 pair 从 `KNOWN_SCHEMA_CONTENT_DRIFT` 移除（18→17,drift-not-stale 测试要求同步后剪除）。
- 新增 `JsonlStore.rewrite_all`（逐行校验 + tmp+replace 原子写）;`_rewrite_runtime_request` 改走它,
  不再裸 `write_text` 绕过校验。

## 验证
- `ruff check`（改动文件）clean。
- **新增/扩充测试**: `test_security_guards.py` +14 例（secret 读/重定向/网络/破坏性/`.asteria` PathGuard,含 allow=true 放行与文件名误报反例）;`test_jsonl_store_rewrite.py` 新建 3 例（校验重写/拒绝越界枚举 fail-closed/packaged schema 接受 auto_applied）;`test_schema_packaging.py` 剪除 runtime_request。
- **红队 battery**: 31/31 攻击命令被拦（含 certutil 之外常见外传、解释器删除、引号 powershell、`.asteria` 篡改）,23/23 合法命令（pytest/npm/git/mypy/`node build/dd-bundle.js`/`python nc_helper.py`/含 `curl` 字样的 commit message）全部放行——0 误报。
- **回归**: unit 863 passed;integration（command/shell/runtime/execute/tool/compact/resume 子集）198 passed;doc_contracts 22 passed。
- 另跑对抗性 red-team 工作流（4 攻击者各攻一条守卫,读真实代码找绕过）—— 结论见下方「红队复核追加」。

## 红队复核追加（2026-07-02 · 第二轮加固）

4 个 opus 攻击者各攻一维（secret-read / network / destructive / self-escalation）,共提 **34 条候选绕过**,
且大多已在真实 shell/真实文件系统上验证「命令生效 + 旧守卫放行」。这暴露第一轮 denylist 的两类问题:

**处置原则（诚实,不打地鼠）**:
- **修 correctness bug**——守卫连自己 denylist 里的项都因平凡混淆而漏掉的,必须修（漏自己列的项=坏,不是「不全」）。
- **补廉价高置信覆盖**——明确的 LOLBin / 破坏动词,一次加进表。
- **不追无限尾巴**——解释器任意代码 payload 无法被静态扫描收住,硬凑正则只会制造假信心 + 误报。**如实标注为不可约残留,指向 sandbox。**

**第二轮 8 项加固（`security/shell_guard.py`）**:
1. **caret 混淆**: `validate()` 开头 `command.replace("^","")`——cmd.exe 把 `^` 当转义并剥除(`type .en^v`→`.env`、`de^l`→`del`),折平后再扫。
2. **目录规则大小写 + 尾点**: `_matches_secret` 逐段 `rstrip(" .")` + 全 `lower()`——Windows/macOS 大小写不敏感且剥尾点,`.Asteria/`·`.ASTERIA/`·`.asteria./` 都归一到 `.asteria`。
3. **path-qualified / 后缀命令名**: 新增 `_command_name`（basename + 去 `.exe/.com/.bat/.cmd/.ps1`）,`_command_words`/`_segment_leaders` 区分「Windows 开关 `/c`」与「unix 路径 `/bin/rm`」——`/bin/rm`·`rm.exe`·`./rm`·全路径 `…/curl.exe` 都还原成裸命令名。
4. **wrapper payload 二次扫描**: 新增 `_wrapper_scripts`——`cmd /c "del x"`·`powershell -c "iwr …"` 里被 shlex 当单 token 的引号脚本,拆出来再过 word/leader denylist。
5. **网络 LOLBin**: NETWORK_COMMANDS 补 certutil/bitsadmin/plink/start-bitstransfer/http/https/wget2/aria2c。
6. **网络深层正则** NETWORK_PATTERNS: `/dev/(tcp|udp)/`、`net.webclient`、`downloadfile|…|uploaddata`、`invoke-webrequest|invoke-restmethod|start-bitstransfer`——收住 bash 裸 socket 与 .NET 一行流。
7. **破坏动词补全**: DESTRUCTIVE_COMMANDS 补 unlink/clear-content/set-content/out-file；DESTRUCTIVE_PATTERNS 补 `os.truncate`、`.（unlink|rm|rmdir)sync(`（node fs）。
8. **重定向无空格漏洞**: `_validate_output_redirects` 正则 `\s+`→`\s*`,`echo x >.env` 这类紧贴 secret 目标不再漏扫。

**复核结果**: 34 候选中 **28 条现被拦**（重放脚本 `scratchpad/redteam_battery.py`,并已固化为 `test_security_guards.py`
4 组参数化回归,共 **82 例通过**）,**23/23 合法 dev 命令 0 误报**（含 commit message 含 `rm`/`curl`、`npx tsc`、`node build/dd-bundle.js`）。全量 unit **863 passed**。

## 残留 / 明确不在 P0 范围（诚实清单）

**核心事实先说**: shell 命令 denylist **不是安全边界,是减速带**。红队用解释器 payload 证明了它必然可绕。以下 11 类现仍可绕过,均归同一根因——**静态扫描无法收住「能跑任意代码的解释器」和「无处不在的覆盖命令」**:

| 残留 | 例 | 为何不硬修 |
|---|---|---|
| 解释器反射/拼接 | `python -c "getattr(__import__('os'),'remove')(…)"`、`open('.ast'+'eria/…','w')` | 运行期才成型,静态不可见,任何正则都能再绕 |
| 解释器内建网络 | `python -c "urllib…urlopen('http://…')"`、`node -e "fetch(…)"` | 同上;URL 也可运行期拼 |
| 解释器截断/删除 | `python -c "open('x','w')"`、`perl -e "unlink…"` | 同上;加 `open('w')` 正则会误杀合法写文件 |
| 无处不在的覆盖命令 | `cp /dev/null x`、`mv src x` | cp/mv 日常必用,拉黑=高误报 |
| 普通文件重定向截断 | `echo hi>important.py` | 拦所有 `>` 覆盖噪音过大;secret 目标已单独收 |
| 远程包执行 | `npx pkg@latest`、`deno run https://…` | npx/deno 是日常 dev 工具,拉黑=高误报 |

- **唯一彻底解**: 把 agent 的 shell 跑进 **sandbox（进程级文件/网络隔离 + 只写 workspace overlay）** —— 即 KEEP_PLACEHOLDER 的 sandbox rollout。denylist 只降低「随手/注入 payload 命中常见工具」的概率,**不能替代隔离**。
- **对 external Beta 的直接建议**: 放量前,Beta 环境的 shell 应 **默认 `allow_shell` 收窄/关闭,或在受限容器内运行**;不要把「denylist 已加固」当成「shell 已安全」。此项应作为放量 DecisionPoint 的前置风险明示。
- approve_similar 假证据、MCP/Skill ask 语义等属 P1 信任修复,不在本批。
