# 完成度重审计（2026-07-18）——对照 S77 基线

**为什么有这份报告**：S77 审计（`S77-commercial-readiness-audit-20260704.md`·实现≈71%）是 7 月 4 日的快照，
此后 changelog 走到 1.2.113（自主环闭合、G 系列 15 条收官、S87/S88 双层写者守卫等），旧数字已失真且
其 P1④/P1⑥ 早被标注过期。「推进到高完成度」需要一个当前的可度量基线——这份就是。

**方法（与 S77 同框架，可直接对比）**：沿用 S77 的 15 子系统拆分与「粗平均、关键项下拉」口径。
每个子系统把 S77 的**逐条扣分断言**交给独立核查代理回**当前代码**验证（只信代码不信文档——
1.2.108 的教训：索引引真源不构成核实），逐条判定 已修 / 仍成立 / 部分修 / 失效，并附 文件:行号 证据。
四个代理并行、互不知晓彼此结论。本报告只汇总；逐条证据在各代理结论中，关键项摘录于 §3。

## 1. 总分

| 子系统 | S77 (07-04) | 现在 (07-18) | 变化 | 一句话驱动 |
| --- | ---: | ---: | ---: | --- |
| 评估/gate/验收 | 55 | 78 | +23 | gate 加真正确性闸（ADR-0018·按真实退出码打分）+ ring_recovery 真栈 nightly；release 闸仍排除真 provider |
| Agent 循环内核 | 67 | 88 | +21 | FSM 退役、`model_driven_turn` 单一活路径；repair/continue/goal-replan 三环进程内闭合、随权限档默认开；auto-finalize 只在真实可执行验证过了才放行 |
| 文档/上手/打包 | 83 | 95 | +12 | LICENSE+license 字段+`Private :: Do Not Upload`；wheel 现建不追踪；真构建门坐实在 release.yml（needs: verify） |
| 安全 | 66 | 76 | +10 | env 擦洗、网络出口门、秘密路径门、替换/wrapper 提取扫描；**无 OS 沙箱仍成立**（唯一 P0） |
| Skills | 72 | 82 | +10 | SKILL.md body 注入执行 + 6 个内置技能；参数契约仍不校验、无模型遵循性测试 |
| 验证/修复环 | 64 | 72 | +8 | review 分改真凭据（模型判断→真验证通过率→诚实 None）；DebugAgent 随 FSM 退役；repair 台账仍未接、skip-review 后门仍在且被 supervised loop 主动用 |
| Studio 前端 | 80 | 86 | +6 | 39 个测试文件 + 4 Playwright spec + G 系列 15 条收官 |
| 多 provider | 66 | 72 | +6 | 零配置默认档=真 minimax、罐头输出诚实标注上浮 route-health；仍缺 Anthropic/Gemini 原生；fake 仍结构性过 model-check |
| 工具执行层 | 80 | 86 | +6 | apply_patch 能建/删文件；只读工具有计量（默认权重 0）；shell 仍非沙箱 |
| Studio 后端 | 87 | 92 | +5 | 500ms 增量 tail（size+seq 去重）、S87 跨 run 守卫、拆出 24 个 lib 模块；脱敏升级为键名结构化+正则兜底 |
| CLI 路由 | 85 | 89 | +4 | 14 命令 curated 分组是设计而非泄漏；maintainer 分隔仍仅展示层 |
| 持久化/Schema | 82 | 86 | +4 | audit_chain 防篡改链落地（**默认关**）；手搓校验器忽略 minimum/pattern/$ref、无 fsync 仍成立 |
| 规划/目标规格 | 70 | 74 | +4 | mid-run replan/steer 进程内闭合；任务分解与质量分仍是关键词启发式（「对 benchmark 名过拟合」未在现码找到证据） |
| MCP | 71 | 74 | +3 | add-server UX（mcp list/enable/disable + catalog）补齐；仍 stdio-only、allowlist fail-open、真传输测试 env-gated |
| 上下文/成本控制 | 78 | 76 | −2 | token 估算 CJK/多模态化、窗口可配、硬保险丝真停；但「压缩」仍只写快照**从不缩活提示**——按证据下调 |
| **粗平均** | **≈71**（算术 73.7 下修） | **≈80**（算术 81.7 下修） | **+9** | 下修理由同 S77：安全（无沙箱）与验证环（台账/后门）仍拖底 |

**结论一句话**：**≈71% → ≈80%**。最大的真实收益是 S77 点名的价值主张本身——「自主闭环」从
「拦截并推荐」变成了进程内真闭环（67→88、55→78）；残余债集中在四处：OS 沙箱（唯一 P0）、
release 闸不含真 provider（nightly 带外承接）、压缩不缩活提示、验证环的台账/后门。

## 2. S77 的 P0/P1 清单现状

| S77 条目 | 现状 |
| --- | --- |
| P0 无 OS/进程沙箱 | **仍成立**（denylist 质量已大幅强化，但 `shell=True` 无进程封禁·`command_tools.py:35-43`）。唯一剩余 P0，按内部发动机定位已降级为加固项 |
| P0 无 LICENSE | ✅ 已修（LICENSE + `pyproject.toml:9` + Private classifier） |
| P0→P1 假默认档 + 无前沿 provider | 部分修：零配置默认=真 minimax、告警可见；仍缺 Anthropic/Gemini 原生；fake 对 `purpose=="model_check"` 仍回 `{"ok": True}`（`fake.py:98-99`）⇒ 结构性过检 |
| P1 自主环未闭合 | ✅ 已修（三环+软保险丝进程内闭合、默认随权限档·`run_command.py:1611/1795`） |
| P1 gate 量结构非正确性 | 大部分修：`gate_status_command.py:544-577` 按真实退出码打分并可 block；**release 闸仍排除真 provider**（`pyproject.toml:53` `-m "not real_provider"`·真栈只在 nightly） |
| P1 S69 验证器空气 + DebugAgent 占位 | DebugAgent 随 FSM 退役=失效；对抗评审现为可派 reviewer 专家（`expert_registry.py:50-59`·模型自选**非强制独立闸**）=部分修 |
| P2 生态休眠 + 发布卫生 | 发布卫生已闭；生态半开（MCP catalog+UX 有了，仍 stdio-only 零默认 server） |

## 3. 仍然成立的债（按咬人程度排序·全部有现码证据）

1. **OS 沙箱缺席**（安全 ①③⑤⑩）：`subprocess.run(shell=True)` 无封禁、`allow_shell` 默认开
   （`templates/policies.default.json:69`）、beta_safe 需显式 opt-in、解释器一行绕扫描（代码自己承认·
   `shell_guard.py:93-94`）。env 擦洗把凭证面收窄了，但架构性缺口未变。
2. **release 闸不含真 provider**：verify/release 全程 `-m "not real_provider"`；真栈证明只在两条 nightly
   （有 key 才跑）。闸的诚实性依赖 nightly 红了有人看。
3. **「压缩」从不缩活提示**：`compact_command.py` 只写快照，`context_budget._compact_boundary` 算出的
   preserve/droppable **无人应用**到发给模型的上下文——名不副实的程度自 S77 未变。
4. **验证环两洞**：`record_repair_attempt` 零调用方（`budget.py:185`·repair 上限形同虚设，实际靠
   迭代保险丝/续跑上限兜底）；`accept --skip-review` 后门在且被 `supervised_goal_loop_command.py:147`
   主动使用。
5. **持久化三件**：手搓校验器忽略 minimum/pattern/$ref（而 `run_loop_summary.schema.json` 真声明了
   minimum=声明被静默忽略）；零 fsync；audit_chain 默认关（`audit_chain.py:33`）。
6. **MCP 三件**：stdio-only；mcp/skill allowlist 空=放行（fail-open·`capability_decision_recorder.py:203-209`，
   与 tool 的 fail-closed 不一致）；真传输冒烟被 env-gate 出 CI。
7. **Skills 两件**：参数契约只展示不校验（`skill_adapter.py:539-543`）；无「模型真的遵循注入指令」的
   任何真跑测试。
8. **规划仍是确定性关键词启发式**（`planner.py` / `task_plan_evaluator.py`·扣固定分值的结构 lint）——
   与 ADR-0016「认知归模型」的方向张力最大的一块存量。

## 4. 本次重审计顺带撞出的新发现（均已另案处置·不混进分数）

- **background run 双 bug**：`local_background_run.py` spawn 的 `python -m asteria_runtime.cli` 是静默
  空操作（cli.py 无 `__main__` 块）⇒ 后台 run 从未真跑过；`_pid_is_alive` 的 `os.kill(pid,0)` 在
  Windows 会**终止**目标进程。发现记于 1.2.111；本报告成文当天已由另一会话修掉（1.2.112）。
- **MCP 子进程不擦洗 env**：`mcp_adapter.py:75` 全环境传给第三方 server，与 shell 路径的
  `sanitize_subprocess_env` 同边界不同姿态。已挂独立任务片。
- 陈旧注释一条：`server.mjs:662` docstring 仍写「every 1.2s」，实际 `TAIL_POLL_MS=500`。

## 5. 对「高完成度」的含义

以内部发动机定位衡量，**管道层（Studio/CLI/打包/持久化）已进 85-95 区间，承诺层（自主环/评估）
已从"拖底"翻到 72-88**。把总分从 80 再往上推，性价比排序就是 §3 的顺序：沙箱（P0·6-12 周）>
release 真栈闸 > 压缩真缩 > 验证环补洞。其余（MCP/Skills/规划启发式）按真 friction 证据拉起即可。
本报告数字的有效期同 S77：**它是快照**，引用前对照 changelog。
