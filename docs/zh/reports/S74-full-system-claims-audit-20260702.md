# S74 全系统「文档声称 vs 代码现实」审计（2026-07-02）

> 触发：用户判断「前端差距大、后端差距应该也不小、架构里说的不一定真的实现了，可能漏洞百出」。
> 方法：12 个维度并行审计（架构分层 / 核心循环 / 工具·MCP·Skills / 上下文 / 评估验收 / 持久化与 schema /
> Studio 证据契约 / Studio 对标主流 / 安全与成本 / 桩代码全扫 / 供应商层 / CLI 表面），每条 critical/high
> 发现再派独立对抗复核代理试图推翻。规模：34 个代理、1235 次工具调用。
> 结果：**22 条 critical/high 全部确认（0 被推翻，2 条降级为 overstated）**，另 145 条 medium/low。
> 主执行侧另行人工抽查实锤了 shell_guard 无保护路径逻辑、server.mjs 罐头 chat 路径两条最重发现。

## 1. 总体判读：不是「漏洞百出」，是「四条裂缝」

「漏洞百出」的直觉**一半对一半不对**，且对错的分布出人意料：

**比预期真（后端核心）**：
- 核心执行环真实：真模型调用（schema 校验+纠错重试）、工具真子进程、candidate workspace 真 git worktree 隔离、
  预算真拦截（model 200 / tool 1000 / 0.90 硬停真的暂停进 DecisionPoint）、replan 上限真绑定、resume 真恢复。
- MCP 是真 stdio JSON-RPC 客户端（本次审计对真实子进程实测通过）；Skill 已从 manifest 桩毕业为真加载 SKILL.md 全文。
- Provider 层是最扎实的子系统：两个真 HTTP 客户端、真 SSE 流式、重试退避、多文件失败证据、167 个相关单测过。
- 持久化核心：JsonStore 原子写+fail-closed 校验，87 个 schema 约 70 个被真实使用。
- 全仓库零 TODO/FIXME/NotImplementedError；三个 triage 锁定占位（remote/并行写/DebugAgent）在代码、CLI、Studio 徽章层都诚实标注。
- CLI 表面：全部文档化用户命令存在且实现真实，maintainer 命令按 HIDE_NOT_DELETE 正确隐藏。

**四条裂缝（洞高度聚集，不是均匀分布）**：

| # | 裂缝 | 一句话 |
| --- | --- | --- |
| ① | **安全强制被超卖**（3 条 critical） | shell 工具无保护路径/网络守卫：`cat .env` 直接读走、`curl` 直接外传；破坏性拦截是浅词表，`find -delete`/解释器 one-liner 全绕过 |
| ② | **权限承诺是标签** | MCP/Skill 的 ask==allow（requires_decision 无消费者）；"Approve similar for this session" 选项零实现，选了等于没选还写 `execution_approval_applied` 假证据 |
| ③ | **前端诚实化未闭环** | chat >15 字含任务词直接罐头模板（不碰模型）；模型失败静默降级、fallback 标注被删成 no-op；"AI Debug Agent" 是关键词模板冒名；compact 自称 summarize 实际只写快照 |
| ④ | **闭环断点 + 能力不可见** | skill/MCP 结果不回灌下一轮（channel filter 丢弃）；/run 掉了 review 步（文档通过标准悬空）；chat 无对话历史（单轮失忆）；runtime 写 40+ 证据文件 Studio 只渲 6 个 |

**对用户三个猜想的裁决**：
- 「前端差距大」——**对**。中断/转向、会话搜索、费用显示、todo 面板、运行态流式全缺；且前端聚集了最多诚实化谎言（罐头 chat、假 AI Debug、"Done." 编造）。
- 「后端差距应该也不小」——**不对，方向错了**。后端比前端真得多；后端真正的差距是①安全强制和②权限语义，以及「做了但用户看不见」（证据可见性）。
- 「架构里说的不一定真的实现了」——**部分对**。分层结构逐层存在且接线；但文档在 ask 三态、自动压缩、fork、目录级指导、多轮对话、审阅步骤上超卖了。

## 2. 确认发现清单（22 条，0 被推翻）

### ① 安全强制（3 critical + 1 high）

| 发现 | 状态 | 证据 |
| --- | --- | --- |
| shell 工具无保护路径/secret 守卫，`cat .env`/`type secrets/k.pem` 实测 ALLOWED，与威胁模型 §6.2「auto 模式也硬拦」直接矛盾 | critical/broken | security/shell_guard.py:60-95（无路径逻辑）、tools/command_tools.py:28-41（仅 ShellGuard 后直接 subprocess shell=True）；对照 file_tools.py:18-19 PathGuard 只管 read_file/list_files |
| allow_network=false 只管 research HTTP 源；shell 里 curl/wget/nc/ssh/git clone 实测全放行 | critical/broken | shell_guard.py:12-95 无网络处理；allow_network 仅 research/sources.py:92,126 |
| 破坏性拦截是全词 denylist：`find . -delete`、`python -c "shutil.rmtree(...)"`、`truncate`、`dd`、引号内 `Remove-Item` 全绕过 | high/partial | shell_guard.py:12-25 词表、:119-133 _command_words 剥引号导致引号内容不匹配 |
| .asteria/ 不在 protected_paths：write_file 可改策略文件自提权（medium 提升关注） | medium | 见 security-cost medium 清单 |

### ② 权限语义（4 high，跨 3 个维度交叉确认）

| 发现 | 状态 | 证据 |
| --- | --- | --- |
| MCP/Skill 的 ask 是 no-op：decide() 产出 requires_decision=True 但全仓库无消费者；McpAdapter/SkillAdapter/gateway 都只拦 deny | high/partial | capability_invocation_policy.py:308-351、mcp_adapter.py:275-292、skill_adapter.py:271-281、tool_execution_gateway.py:119-120 |
| "Approve similar for this session" 选项渲染但零代码兑现；has_execution_approval 只认 approve_once；resume 对其他选项直接 return 却仍记 `execution_approval_applied` —— 用户面谎言+假证据 | high/broken | runtime_policy.py:249-254 vs :150-162；resume_command.py:396-414,223-227 |

### ③ 前端诚实化（2 critical + 3 high）

| 发现 | 状态 | 证据 |
| --- | --- | --- |
| chat 罐头冒充：>15 字含 实现/修复/重构/添加/创建/更新 直接返回模板不调模型；模型失败落 localOutcomePlanAnswer 整套模板计划无披露；appendModelNotice 被删成 no-op；streaming_mode='local_fallback' 无前端消费——违反产品设计 §3 核心诚实承诺 | critical/broken | server.mjs:984-985,1016-1032,1208-1265,889 |
| 无中断/转向运行中 agent：全 studio/src 无 stop/cancel UI/API，server 无 kill 路由——主流第一天必撞 | critical/missing | server.mjs:1579-1615；grep 全量 |
| "AI Debug Agent" 卡无 AI：debugAnswerFor() 三分支关键词模板，无模型无请求 | high/stub | AiDebugAgentCard.tsx:16-17,30,53-70 |
| 运行态模型流被占位句遮蔽：LiveStream 对 phase!=='chat' 把真 delta 换成 'Putting together a plan…'（chat 相位流式是真的，链路本身通） | high/partial(overstated) | LiveStream.tsx:50-62 vs ConversationTurn.tsx:122-144 |
| 无会话搜索（产品设计 §2 自己声称 Sidebar 含 Search） | high/missing | SessionList.tsx:53-66 |
| compact 文案谎报：Studio 说 "Summarize older turns to free context space"，CompactCommand 只聚合快照、零摘要零释放；硬停出口还推荐 compact 这个救不了它的药方 | high/partial | server.mjs:530-544、compact_command.py:42-96、execute_command.py:1613-1615 |

### ④ 闭环断点与证据可见性（7 high）

| 发现 | 状态 | 证据 |
| --- | --- | --- |
| skill/MCP 结果不回灌下一轮：_refresh_harness_observations 每轮用 channel=='execution_chain' 过滤重载,而 skill/MCP 分支写的是 channel='tool'——任何本地工具调用后 SKILL.md 指令/MCP 响应即被冲掉；无跨轮测试 | high/broken | execute_command.py:2322,2748-2758、agent_harness.py:278-283、tool_execution_gateway.py:49-75 |
| /run 不再调 review：文档通过标准「eval_report overall==pass」悬空,diagnostics.review_status 恒 None,run_command 还留着过滤已删 review 步的死代码 | high/partial | run_command.py:173-275,890-896、real_model_smoke.py:1088-1093 |
| chat 无对话历史：ChatCommand 单问零上文,Studio 每条消息新起进程,前几轮只用于意图路由 | high/missing | chat_command.py（grep 零命中）、server.mjs:976-1027 |
| memory_lesson_reuse 验收场景是自断言剧场：harness 自己写 lesson+prompt 再断言自己写的字符串,却计入 memory_effectiveness 能力覆盖 | high/stub | real_model_acceptance.py:988-1034、acceptance_gate_command.py:272-292 |
| runtime_request 原始 write_text 绕过校验,写入仅根 schema 有的 auto_applied 枚举——装成 wheel 后一次 auto-apply 毒化 jsonl,后续 resume/compact/validation 全崩 | high/broken | runtime_policy.py:447,516-529、双 schema enum diff |
| Inspector 承诺 raw evidence:服务端组装 9 类前端零渲染;40+ 证据文件服务端读一半、UI files.slice(0,6);capability_decisions.jsonl 有写无读 | high/partial | server.mjs:2601-2646、EvidenceExplorer.tsx:492-496,590-605 |
| plan 开场事件误标 final:conclusion channel 默认回落 transcript_kind='final',run 一启动主线程就出现 Result 气泡、叙事判 completed | high/broken | plan_command.py:188-197、user_progress_logger.py:286-287、narrative.ts:80,186-188 |
| 事件同步层 broken:直播 tail 把 event_id 覆盖为裸 upe-XXXX 跨 run 冲突;回放双源合并只过滤 5 类,tool_start/final_answer 双份保留 | high/broken | server.mjs:1542-1547,2296-2319,2389-2399、eventUtils.ts:11-16 |

### 供应商层边缘（高价值 medium/broken，含本会话自产 bug）

- **D-3 告警假阴性（本会话 422ad38 引入的告警有 bug）**：全局 AGENT_MODEL_PROVIDER=minimax + 仅 CHEAP=fake 时不告警——default_routes 与 factory 对未配置 cheap 档的判定不一致，诊断报 'fake' 而真实失败方是 MiniMax。
- route_fallback 真实 run 路径仍只在内存（已知问题再确认）。
- worker_transport='tool_use' 在默认流式下端到端 broken（tool_call delta 被丢）。
- `--model-strategy local` 是 no-op 桩。

### 其余重点 medium（节选）

- 修复预算死接线：record_repair_attempt() 全仓库无人调用,max_repair_attempts_* 永不生效。
- 4 个已注册工具（glob/diff_workspace/todo_read/todo_write）被过期 capability-kind 映射硬拒,模型表面却在广告。
- run_command 对 nonzero 退出+usage 输出自动判 pass（影响验收计分）。
- `init` 重跑无条件覆盖用户改过的 policies.json,与「不覆盖用户手写内容」验收矛盾;init --force 是 no-op。
- max_total_minutes_per_goal 全 profile 定义、无处强制。
- TurnFinal 缺文本时编造 "Done."（工程设计 §7.2 逐字相反）。
- run detail 只读 user_progress 尾部 120 条,长 run 开头被静默截断。
- session↔run 关联靠 stdout 正则+mtime 窗口猜,session_id 字段存在却写 null。
- 死 MCP server（命令不存在）直接炸 run,与「降级为无工具」声称相反。
- fork 动作文档声称、全仓库零代码。
- 自动压缩只有测量+建议,无执行;两个 compaction 策略旗标接空。

## 3. 研发计划重排（P0→P4）

原顺序（D5 → re-tag v0.2.0a2 → Track C → Track A）**必须重排**：安全裂缝不堵，
外部 Beta 用户机器上一句 `cat .env` 就是真实泄密事故；带着「approve_similar 假证据」
「罐头 chat」去 re-tag 也不诚实。

### P0 安全止血（最高优先，1–2 slice，全在非 DO_NOT_TOUCH 的 security/tools 层）
1. shell 工具接保护路径/secret 预扫（command_tools 执行前对 protected_paths + secret 模式扫描 token）。
2. ShellGuard 接 allow_network：curl/wget/nc/ssh/scp/git-remote 类命令按策略 gate。
3. 破坏性词表加固：find -delete / truncate / dd / shred + 解释器 one-liner（python/node/powershell -c 载荷检查）。
4. protected_paths 纳入 `.asteria/`（防策略自提权）。
5. runtime_request 修复：packaged schema enum 补 auto_applied + _rewrite_runtime_request 走校验写。

### P1 信任修复——把说出去的话兑现或收回（2–3 slice）
1. approve_similar_for_session：先移除选项+停记假 effect（后续再实现 session 级指纹放行）。
2. MCP/Skill ask 三态：requires_decision 接入既有 DecisionPoint 机制（与 shell 审批同型），或文档降级为「记录性 ask」。
3. chat 罐头三连修：删 looksLikeTask 短路；恢复 appendModelNotice 真实现或前端消费 streaming_mode='local_fallback' 渲染降级徽章；localOutcomePlanAnswer 加未连模型披露。
4. AI Debug Agent 卡改名去 AI 冒名（或接真模型端点）。
5. compact 文案对齐现实（快照≠压缩）+ 硬停出口不再推荐 compact —— **吸收并取代原 D5**（原 D5 的英文标题/final 误标修复一并做：plan 开场事件显式 transcript_kind，conclusion→final 默认收窄到 phase==result）。
6. TurnFinal 删 "Done." 编造。
7. D-3 告警假阴性修复（default_routes 与 factory 对 cheap 默认判定归一）。

### P2 核心闭环断点（2–3 slice）
1. skill/MCP 观察回灌：gateway skill/MCP 分支写 execution_chain turn 事件（镜像 _record_harness_turn）+ 两轮跨回合测试断言 SKILL.md 指令出现在第 2 轮 prompt。
2. /run 接回 review 步或改文档通过标准 + 删死代码。
3. 修复预算接线（record_repair_attempt 真调用）。
4. 4 个被硬拒工具的 capability-kind 映射修复。
5. route_fallback 落盘为可消费证据。
6. chat 有界对话历史（近 N 轮进 ChatCommand）——「无历史」是对标主流最大的单点产品缺陷之一。

### P3 桌面赌注（前端，按撞墙频率排序）
1. **Stop/中断**：server 记 child pid + POST stop 路由 + Composer 运行时 Send→Stop。
2. 会话搜索（SessionList 前端过滤起步，成本极低）。
3. 运行态真流式（LiveStream 不再用占位句遮蔽 delta）。
4. 累计 token/费用显示（cost_report 数据已有，纯渲染）。
5. Inspector 渲染已组装的 raw_evidence + files 列表不截断（capability_decisions 等后端能力可见化——即缓期的 B7/C8/D9 的正确解法）。
6. 事件 id 命名空间统一（runtime-<runId>-<upe-id>）+ 回放合并按 id 去重。

### P4 债务与放量前提
1. Track C：18 schema 漂移收敛、mypy 129；JsonlStore fail-open→fail-closed 评估。
2. memory_lesson_reuse 场景重写或摘除能力计数;run_command usage 自动 pass 收紧;review 计分深度（read_file 不算验证通过）。
3. init 幂等修复（不覆盖用户 policies.json）。
4. 文档降级批改：fork/目录级指导/自动压缩/多 provider 默认路由等超卖点对齐现实。
5. **Track A 外部 Beta 邀请：放在 P0+P1 完成之后**——这是顺序上最重要的一条改动。
6. re-tag v0.2.0a2：P0+P1 落地后作为诚实 capstone。

### 冻结不变
新编排 Wave、parallel_writes 全局默认、无 friction 证据的 Studio 新功能照旧冻结。
P3 各项均为主流 table stakes 补齐/诚实化，不属于「新功能」范畴。

## 4. residual

- 145 条 medium/low 全文见审计工作流输出（本报告只收编 hot 项）；后续 slice 落地时按维度回查。
- 本报告不改 研发总计划.md 的 ACTIVE_SLICE/执行顺序——等用户对 §3 重排拍板后再回写主计划。
