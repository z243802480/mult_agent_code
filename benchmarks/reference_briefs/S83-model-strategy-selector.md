# S83 — G8-a 模型档位选择器（Studio 侧接通 `model_strategy`）

## 一句话

CLI 早有 `--model-strategy`（auto/quality/economy/local），运行时真消费它；**Studio 从来不发它**，
所以经 Studio 起的每一个 run 都只能吃 `auto`——这一刀把选择权交还给用户。

## 缺口的实证（本刀开工前核实，非推断）

| 环节 | 现状 | 证据 |
| --- | --- | --- |
| CLI 入口 | `run`/`plan`/`chat` 三个 parser 都有 `--model-strategy`，choices `auto/quality/economy/local`，default `auto` | `cli.py:272`/`:295`/`:788` |
| CLI → 命令 | `args.model_strategy` 真传进 `RunCommand` | `cli.py:2023` |
| 命令 → 配置 | `RunCommand` → `PlanCommand`（`run_command.py:260`）→ `build_run_config(model_strategy=…)` | `core/run_config.py:20-48` |
| 配置 → 策略 | `build_run_config` 写 `model_strategy_profile` 进 `run_config.json` | `core/run_config.py:40` |
| 策略 → 消费 | `apply_run_config` 把它并进 policy；`RuntimeProfileBuilder` **真读**（选模型时用） | `run_config.py:104-106`；`runtime_profile_builder.py:162`/`:401`/`:434` |
| 暖路 worker | **已经在读** `request.get("model_strategy", "auto")` | `studio_worker.py:113` |
| **Studio 前端** | **零引用 `model_strategy`** | `grep -rn model.strategy studio/src` → 空 |
| **Studio BFF** | **零引用** —— 冷路命令不带 flag、暖路 JSON 不带字段 | `grep -rn model.strategy studio/lib studio/server.mjs` → 空 |

⇒ **缺口只在最后两行**。后端从 CLI 到模型选择整条链路早已通，唯独 Studio 这个入口没接上去；
它起的 run 一律走 argparse 的 `default="auto"`。这不是"功能没做"，是**一根线没接**。

**这与 G8-b 是两码事**：`policy["model_routing"]`（具体 provider/model 覆盖的落点）**零生产消费者**，
`_model_routing_overrides()` 硬编码 `return {}` 且带一段刻意的设计注释（`run_config.py:116-122`：
"别在 run 创建时把路由一把钉死，让 RuntimeProfileBuilder 综合任务形状/风险/能力反馈/预算决定"）。
本刀**不碰它**——那条路要么推翻该注释并记 ADR，要么设计成窄覆盖，是真设计活，不是接线活。

## 用户决策（2026-07-17 拍板）

G8 = **两者都要**：**档位默认**（本刀 G8-a）+ **可覆盖具体模型**（G8-b，另刀）。
"档位默认" ⇒ 落在**设置面板的持久化默认**，不是 Composer 的逐条消息切换。
（Composer 已有权限档 cycle；再塞第二个 cycle 是给主输入框添堵，且用户要的词是"默认"。）

## 做什么

1. **词表单一真源** `studio/src/modelStrategies.ts`——照 `permissionTiers.ts` 的样子（id/label/hint/
   detail + `resolveModelStrategy` + `isModelStrategyId`）。id 必须与 CLI 的 choices **逐字**相同。
2. **设置面板控件**：`SettingsPanel.tsx` 的 `ModelSection`（现为**纯只读**：只展示提供方就绪状态 +
   近期路由活动·`SettingsPanel.tsx:232`）顶部加一个 radiogroup，照 `PermissionSection` 的
   保存/busy/error 手感（`SettingsPanel.tsx:125-154`）。
3. **持久化**：`POST /api/studio/settings` 目前**强制**要求 `permissionMode` 且对其它字段一律 400
   （`server.mjs:493-501`）——改成按字段校验的 patch 语义，**保持既有 `{permissionMode}` 请求逐字兼容**。
   `buildSettingsPayload()` 加 `modelStrategy`（非法值退化到 `auto`）。
4. **BFF 透传（本刀的心脏）**：冷路 `withModelStrategy(command, strategy)` 照 `withPermissionLevel`
   的 splice 模式；暖路 `warmRunParams(mode, strategy)` 多带一个 `model_strategy` 字段。
   **两路必须同源同输入**——否则又是两份真源（1.2.103 刚栽在这上面）。

## 不做什么（诚实边界）

- **不做 G8-b**（具体 provider/model 覆盖）——见上。
- **不加 Composer 逐条切换**——用户要的是"默认"。
- **不碰 `_model_routing_overrides`** 的设计注释。
- **不动 `plan`/`chat` 命令**——它们的 parser 有这个 flag，但 Studio 的 plan/chat 是另一条路径，
  没有证据说用户想在问答里选档位。等证据。

## resume 不丢：由构造保证（已核实，不靠"应该吧"）

`execute_command.py:282` 调 `effective_policy_for_run` → `load_run_config(run_dir)` → **从磁盘读**
`run_config.json` 里那份 `model_strategy_profile`。所以档位在 run 创建时钉进文件，之后
resume / continue / execute 全都读同一份，**不经过 CLI 参数默认值**。
（这正是 `_permission_mode` 那段注释所说的同一个机制——权限档当初丢就丢在没读回它·404280f。）

## 验证判据（DoD）

- [ ] `run-flags-unit.mjs` 新增：**冷路 flag 与暖路字段对同一档位得出同一值**，遍历全部 4 档 + 非法值。
      （这是本刀唯一的防漂测试——它是 1.2.103 那条 `permission_level` 测试的同构体。）
- [ ] `withModelStrategy` 的边界与 `withPermissionLevel` 对齐：无 `run` token 不动、已有 flag 不重复加、
      空值不动。
- [ ] settings POST 的 patch 语义：只发 `permissionMode` 仍绿（**回归**）、只发 `modelStrategy` 绿、
      非法值 400、两个都发绿。
- [ ] `vitest` / `tsc` / `eslint` 净（前端有真改动，这次不是仪式）。
- [ ] 全量 `pytest`（本刀**不改 Python**，但 settings 契约测试可能覆盖）。
- [ ] **真跑一遍**：起 BFF，改设置为 `economy`，发一条消息，`grep model_strategy` 落到
      `run_config.json`——**不许用推断代替探针**（1.2.103 的教训：wire 测绿 ≠ 用户路径能走到）。

## 命名：`permission-level.mjs` → `run-flags.mjs`

模块的职责本刀翻倍（不再只有权限档），而 `warmRunParams` 是两个选择**共用**的载体——拆两个文件
会把"必须同源"这条不变量拆散。留旧名则是一个名字撒谎的文件（有人 grep `withModelStrategy` 找不到它）。
改名成本 = 2 处 import + 1 个测试文件名 + `package.json` 脚本 + `run-smokes.mjs` 注册行 + 2 处注释提及。
**这不是无关重构**——是本刀直接导致的作用域变化。

## 教训继承

- 子型 g「验了组件，声称了系统」：本刀的 DoD 最后一条是**用户真实路径**的探针，不是模块 wire 测。
- 冷/暖两路 = 两份真源的常设陷阱：任何"Studio 的选择要到达运行时"的东西，**从落地第一天就要有
  那条遍历式相等测试**，否则漂移是静默的。
