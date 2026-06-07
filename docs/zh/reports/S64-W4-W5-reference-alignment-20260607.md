# S64 Wave 4/5 主流参考对齐调研（编码前必读）

**日期**：2026-06-07  
**状态**：reference gate — **Wave 5 编码冻结，须先读本报告**  
**原则**：学机制不抄形态（`AGENTS.md` · `CC_ORCHESTRATION_ALIGNMENT.md`）

---

## 1. 为什么需要本报告

Wave 0–4 已按 DecisionPoint + 隔离 probe 推进，但若不对照 **Cursor / Codex / Claude Code** 的**分层机制**，容易把：

- 「同 workspace 多写者默认并行」误当成主流；
- 「Coordinator gray probe」误标成 CC **Dynamic Workflows**；
- Wave 5 简化成「把 CLI `parallel_writes` 默认改 true」。

本报告基于 **2026-06 公开官方文档**，给出 Asteria 下一档的**正确映射**。

---

## 2. 三家并行模型（四层对照）

| 层 | Claude Code | Cursor | Codex | 共同规律 |
| --- | --- | --- | --- | --- |
| **L0 默认** | 主 loop 逐 turn | 前台 Agent | 单会话为主 | **默认串行、单写者** |
| **L1 loop 内 subagent** | 模型每 turn spawn；可选 `isolation: worktree` | `/multitask` 异步 subagent 舰队 | subagent **显式触发**；`max_threads` 默认 6 | **小并行、模型语义、有上限** |
| **L2 隔离并行写** | git worktree / subagent worktree | Cloud/Background Agent **独立分支**；worktree UI | 云 sandbox **或** 本地 worktree + 独立 `CODEX_HOME` | **并行写 = 隔离副本 + 事后 merge/PR** |
| **L3 编排下沉脚本** | **Dynamic Workflows**：Claude 写 JS，runtime 执行；16 并发 / 1000 agent/run | Agents Window 编排（产品 runtime） | `spawn_agents_on_csv` 批处理；manager 协调 | **计划不在主 context；可恢复、可复跑** |

**没有任何一家**把「同一 working copy 无隔离多写者默认打开」作为 Beta 默认。

### 2.1 Claude Code（官方）

| 机制 | 要点 | 来源 |
| --- | --- | --- |
| Subagent | 模型委派；`isolation: worktree` 给独立 git worktree；结果回主会话 | [Subagents](https://code.claude.com/docs/en/sub-agents) · [Worktrees](https://code.claude.com/docs/en/worktrees) |
| Dynamic Workflows | **JS 脚本**编排；中间态在 script variables；主 context 只见最终结果；≤16 并发、1000/run；**research preview**；可用 `/config` 关闭 | [Workflows](https://code.claude.com/docs/en/workflows) |
| 与 subagent 区别 | subagent：**Claude 每 turn 决定**；workflow：**脚本决定** loop/branch | Workflows 文档对比表 |

### 2.2 Cursor（官方 / changelog）

| 机制 | 要点 | 来源 |
| --- | --- | --- |
| Background / Cloud Agent | 云端 Ubuntu VM；**独立 `agent/` 分支**；输出 PR | 产品文档与 changelog |
| `/multitask` | 请求拆给 **async subagent 舰队**并行，而非排队 | [Changelog 2026-04-24](https://cursor.com/changelog/04-24-26) |
| Worktrees | Agents Window 内 **分支隔离**；一键 promote 到 foreground | 同上 |
| 并行上限 | Pro 档常见 **≤8** 并发 cloud agent（社区/文档口径） | — |

### 2.3 Codex（OpenAI 官方）

| 机制 | 要点 | 来源 |
| --- | --- | --- |
| Subagent | **默认开启能力**，但 **仅用户显式要求时 spawn**；`agents.max_threads` 默认 **6** | [Subagents](https://developers.openai.com/codex/subagents) |
| 角色 | default / worker / explorer；TOML 定义 | 同上 |
| 隔离 | **云 sandbox**（delegated）；CLI 并行常用 **git worktree** + 独立 session 目录 | 开发者文档与社区实践 |
| 批处理 | `spawn_agents_on_csv`：一行一 worker | 同上 |

---

## 3. Asteria 已做 vs 主流（诚实对照）

| Asteria Wave | 实际交付 | 更接近哪家哪层 | 偏差风险 |
| --- | --- | --- | --- |
| W0 | session_agent 单写者 | L0 ✅ | 低 |
| W1 | strong route + spawn eval | L1 抉择护栏 ✅ | 低 |
| W2 | 隔离 `dual_disjoint` + S32 rollback | L2 **probe** ✅ | 低 |
| W3 | catalog gray `spawn_parallel_workers` | L1→L2 **入口**（strong 选中后才走） | 中：仅 maintainer |
| W4 | `orchestration_workflows_gray` + S23 real_disjoint 隔离 probe | **L2 资格门**，非 L3 | **高：命名像 CC Workflows，实现不是** |

### 3.1 Wave 4 命名修正（重要）

当前 Wave 4 **不是** Claude Code **Dynamic Workflows**（L3），而是：

```text
maintainer 级「真实 disjoint worker 管线」资格门
= Phase 5 S23 real_disjoint + 路由回归 + policy flag
```

**CC Dynamic Workflows 等价物**在 Asteria 应为 **defer 的独立 slice**：

- 可复跑 orchestration **脚本/清单**（非 turn-by-turn 主 loop）；
- 中间态落 **script/runner 变量或 JSONL**，不进主 Agent context；
- 上限、checkpoint、resume 由 **runtime 执行器** 管，不是 `parallel_writes=true`。

建议在文档中把 W4 读作 **「L2 生产资格门（mislabel: workflows）」**，L3 另开 **S65+ Dynamic Orchestration Script**（未启动）。

---

## 4. Wave 5 应是什么（调研结论，非实现承诺）

### 4.1 不应做（三家都不做）

| 错误方向 | 原因 |
| --- | --- |
| CLI `parallel_writes` **默认 true** | 无 isolation = 与 Cursor/CC/Codex 相反 |
| 跳过 merge/promotion/PR 式审查 | Cursor 默认 PR；Asteria 有 merge gate |
| keyword/文件数自动拆 worker | 三家均强调语义/显式委派 |
| 把 W4 probe 当成「已开并行写生产」 | 只是 maintainer 资格 |

### 4.2 Wave 5 正确目标（建议重命名）

**Wave 5 = L2 隔离并行写「生产路径」**，不是「默认并行」：

| 条件 | 对齐参考 |
| --- | --- |
| **隔离单元** | candidate workspace / worktree（≈ CC worktree、Cursor 分支、Codex sandbox） |
| **触发** | 显式：`--parallel-disjoint-writes` / strong route 选中 / maintainer validation-run | ≈ Codex 显式 spawn |
| **合并** | merge gate + promotion + 可选 DecisionPoint | ≈ Cursor PR |
| **默认** | `parallel_writes` **仍 false**；`real_disjoint_write_workers` 仅 validation-run 或显式 flag | ≈ 三家 L0 |
| **证据** | 本仓库 `.asteria/validation_runs/` 真实 provider disjoint 场景 | 非 temp-only probe |

### 4.3 Wave 6+（L3，单独 slice）

| 能力 | CC 等价 | Asteria 方向 |
| --- | --- | --- |
| 可复跑编排脚本 | Dynamic Workflows `.js` | maintainer `orchestration_manifest.json` + runner（**S66 brief** ✅） |
| 并发上限 | 16 / 1000 | policy `max_parallel_workers_per_run` |
| checkpoint/resume | workflow runtime | runner JSONL ✅ |
| live worker 执行 | workflow runtime spawn | Wave 7 live band ✅ |
| 对抗验证 | adversarial subagents in script | loop subagent + merge，defer 专用 runner |

**禁止**用 `agent_loop.parallel_writes=true` 一次开关假装完成 L3。

---

## 5. 编码前 Checklist（Wave 5+ 强制）

在改 `parallel_writes` 默认、`real_disjoint_write_workers` 全局 enable、或新增 workflow runner 前：

- [ ] 读本报告 + [`S64-parallel-rollout-research-20260607.md`](./S64-parallel-rollout-research-20260607.md)
- [ ] 更新 [`benchmarks/reference_briefs/S64-orchestration-wave4-workflows-probe.md`](../../benchmarks/reference_briefs/S64-orchestration-wave4-workflows-probe.md) 命名脚注（L2 非 L3）
- [x] 新 brief：**S65-isolated-parallel-write-production-path**（Wave 5）
- [x] 新 brief：**S66-dynamic-workflows-runner**（Wave 6 L3）
- [x] DecisionPoint 议题：隔离路径 vs 默认 on（`decision-orchestration-parallel-0004`）
- [x] 本仓库 validation_runs 证据（Wave 5 probe）
- [ ] doc contract：无 domain keyword dispatch

---

## 6. 对当前代码的建议（不立即改行为）

| 项 | 建议 |
| --- | --- |
| `orchestration_workflows_gray` | 文档注明 = **L2 maintainer 资格**，非 CC Workflows 引擎 |
| Wave 5 实现 | **暂停**「默认 parallel_writes」；先做 **worktree/candidate 显式路径** |
| L3 Dynamic 编排 | 单独立项 S65+，参考 CC workflows **机制**（script-side state），非移植 JS runtime |
| Studio | 并行任务应显示 **隔离单元 id + merge 状态**（≈ Cursor Agents Window） |

---

## 7. 参考链接

- Claude Code Workflows: https://code.claude.com/docs/en/workflows  
- Claude Code Worktrees: https://code.claude.com/docs/en/worktrees  
- Claude Code Subagents: https://code.claude.com/docs/en/sub-agents  
- Cursor Multitask / Worktrees: https://cursor.com/changelog/04-24-26  
- OpenAI Codex Subagents: https://developers.openai.com/codex/subagents  

---

## 8. 结论（给用户）

1. **你的提醒是对的**：Wave 5 若直接「默认打开并行写」会 **走偏**；主流是 **隔离 + 显式 + merge**。  
2. **Wave 4 已完成的价值**仍在：real_disjoint 隔离 probe + catalog/workflows gray **资格门**。  
3. **下一档正确做法**：先写 **S65 brief + validation-run 生产证据 + 隔离并行写显式路径**；**不要**先改 CLI 默认。  
4. **CC Dynamic Workflows 级**应作为 **Wave 6 / S65+** 独立 slice，与 Wave 5 分开。
