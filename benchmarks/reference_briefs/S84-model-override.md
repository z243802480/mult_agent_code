# S84 — G8-b 覆盖具体模型（per-run·per-tier 模型名覆盖）

## 开工前的调研推翻了路线图写的路（本节是本 brief 最重要的部分）

路线 §G8 与 AGENTS §2 都写着 G8-b 的两条路：**(b)** 给 `policy["model_routing"]` 补消费者，或
**窄扩 (a)** `model_strategy_profile`。**两条都不成立**——2026-07-17 读代码核实：

### ① `model_routing` 是 **purpose→tier**，不是 tier→model

policy 里它**有真实默认值**（`.asteria/acceptance/.../policies.json:76`）：

```json
{"goal_spec":"strong","planning":"strong","coding":"medium","summarization":"cheap", ...}
```

⇒ 给它补消费者得到的是「**按用途钉档位**」，**不是**「用 glm-4.6」。路线图把这两件事混为一谈了。
`model_strategy_profile` 同理——它整层都在选**档位**（`_model_selection` / `_default_model_tier` /
`_strategy_adjusted_tier` / `_explicit_model_tier` 全部返回 `cheap|medium|strong`）。
⇒ **"具体模型"在 policy 这一层根本没有落点**，两条路都停在档位上。

### ② 那条设计注释**没有禁止**用户覆盖——我此前把它读窄了

`core/run_config.py:116-122` 原文：

> User-facing strategies are policy biases, not a fixed purpose->tier route table.
> **Explicit project/user overrides may be added here later**, but the default path
> should let RuntimeProfileBuilder combine task kind, risk, capability feedback,
> and budget instead of clobbering all model routes at run creation time.

它防的是**「策略档位去 clobber 路由」**，而"显式的项目/用户覆盖"是它**明说可以后加**的。
⇒ AGENTS/路线里写的「与设计注释冲突 ⇒ 要么推翻它并记 ADR」是**我 1.2.101 核实时只读了前半句**
造成的误判。**无需 ADR，无需推翻任何东西**。（同 bug class：把源里没说的写成源里说了。）

### ③ 真正的机制在 policy 之外：**tier→model 由 factory 从 env / 本地路由文件解析**

```
task ──(RuntimeProfileBuilder：任务形状+策略+能力反馈)──> tier (cheap|medium|strong)
tier ──(models/factory.py `_routes_from_env`)──────────> provider + model_name
```

- `create_model_client(run_dir, validator, budget)` **完全不接收 policy** ⇒ 这才是
  `policy["model_routing"]` 零消费者的**物理原因**（不是"没人写消费者"，是这层压根没有 policy 输入）。
- 模型名来自 `_env(env_prefix, "NAME")`（即 `AGENT_MODEL_{TIER}_NAME`），
  env 缺失时回落 `models/local_route_config.py` 的本地路由文件（`~/.asteria/model.routes*.json`）。

## 决定：做什么

**G8-b = per-run、per-tier 的「模型名覆盖」**，经 `run_config.json` 落盘 ⇒ 与 G8-a 同构
（同一条通道、同样 resume 安全、同样冷/暖同源）。

语义：**保留该 tier 已配置的 provider / base_url / API key，只换 model_name**。
例：strong 档配的是 zhipu 的 glm-5.1 → 本 run 覆盖成 `glm-4.5-air`。

## 明确不做（诚实边界，不是偷懒）

- **不做 provider 覆盖**。凭证是**按 env_prefix（即按 tier）**配的：把 strong 档的 provider 从 zhipu
  改成 minimax，`MiniMaxSettings.from_env(env_prefix="AGENT_MODEL_STRONG")` 会去读
  `AGENT_MODEL_STRONG_API_KEY`——那是**一把 zhipu 的 key**。⇒ provider 覆盖**在当前凭证模型下无法安全表达**，
  需要先有"每个 provider 各自的凭证"的故事。**记为独立项，不在本刀假装做掉。**
- **不做 Studio 编辑本地路由文件**（哪个 provider+key backs 哪个 tier）。那是**另一个功能**（全局·安装期·
  **含密钥**·AGENTS §10 保护路径）。与本刀的 per-run 覆盖是两件事，别合并。
- **不给 `model_routing`（purpose→tier）补消费者**。它是 `_default_model_tier` 的一份死的平行实现，
  该不该合并是另一个问题，**与"覆盖具体模型"无关**。

## 怎么做

1. **run_config 新字段** `model_name_overrides`：`{tier: model_name}`。**不叫** `model_route_overrides`
   ——与既有的 `model_routing_overrides`（purpose→tier）一字之差会害死后来人。
   两份 schema 都加（**仓库根 `schemas/` + `src/asteria_runtime/schemas/`·已知双份陷阱**）；
   `additionalProperties` 未设 ⇒ 加字段是**增量的**，旧 run_config 仍合法（不设 required）。
2. **factory 应用覆盖**：`create_model_client` **已经收到 `run_dir`**（`plan_command.py:212`），
   且 run_config 在 `:189` 就已落盘 ⇒ 直接 `load_run_config(run_dir, validator)` 读覆盖。
   **resume 安全由构造保证**，与 G8-a 同一个理由。
   应用手段=**`dataclasses.replace(settings, model_name=override)`**：
   `OpenAICompatibleSettings` / `MiniMaxSettings` 都是 `@dataclass(frozen=True)` 且有 `model_name` ⇒
   **零触碰 `openai_compatible.py`**（另一会话正在改的文件·硬约束）。
3. **CLI**：`--model-name TIER=NAME`（可重复）。
4. **Studio**：ModelSection 现有的 tier 就绪列表**每行加一个模型名输入框**（占位符=当前解析到的模型名），
   走 G8-a 的 settings patch 通道持久化。
5. **BFF 冷/暖同源**：照 `lib/run-flags.mjs` 的既有模式加一对，**补交叉一致性测试**。

## 验证判据（DoD）

- [ ] python 单测：有覆盖→client 的 `model_name` 是覆盖值；无覆盖→与今天逐字相同（**回归**）；
      未知 tier / 空值 / 垃圾值→**忽略而非崩**（一个手改坏的 run_config 不许让 run 起不来）。
- [ ] `run-flags-unit.mjs` 交叉一致性扩到三个选择（tier × strategy × override）。
- [ ] `settings-patch-smoke.mjs` 扩：新字段的 patch 语义 + 非法值门口拒绝。
- [ ] **真实用户路径探针**：Studio 里填 `strong=X` → 发消息 → `run_config.json` 落 `model_name_overrides`
      → **`model_calls.jsonl` 证据里真用了 X**（这是路线 §G8 写死的验收词："model_calls 证据里真用了所选模型"）。
      ⚠️ 冷/暖两路各验，**且暖路必须证明它真走了暖路**（结果相同 ≠ 走了那条路·1.2.103 的坑）。
- [ ] 全量 pytest / vitest / smokes / tsc / eslint。

## 分刀

本刀（G8-b-1）= **①②③ + 单测**（运行时通道 + CLI，可用真 run 验到 model_calls）。
下一刀（G8-b-2）= **④⑤ + 探针**（Studio UI + BFF 冷暖 + 真实用户路径）。
理由：G8-a 刚教过"后端通了但没人接 = 死通道"，所以两刀**必须连着做完**，不许停在①。
但一刀做完整个链路的 diff 太大、验证会糊——分两刀各自可验、各自可回滚。
