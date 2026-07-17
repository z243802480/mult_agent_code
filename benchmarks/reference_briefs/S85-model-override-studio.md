# S85 — G8-b 刀二：把「钉死模型」接到用户面前（Studio UI + BFF）

## 为什么必须紧接刀一

刀一（1.2.105）把运行时通道修通了：`run_config.model_name_overrides` → `create_model_client` →
`dataclasses.replace(settings, model_name=…)`。**但 Studio 不发它**，所以今天它只有 CLI 能用。
这正是 G8-a 开工时撞见的形状（**1.2.103：warm worker 通了两天、零 run 经手**）。
**后端通了但没人接 = 死通道**，两刀之间不留过夜。

## 已核实的接入点（开工前查的，不是猜的）

| 位置 | 事实 | 证据 |
| --- | --- | --- |
| 占位符数据源 | `doctor.routes[tier]` 的字段名是 **`model`**，不是 `model_name` | 真跑 `doctor --json`：`strong: provider=glm model='glm-5'`；`medium/cheap: provider=minimax model='MiniMax-M2.7'` |
| 档位列表 | `doctor.routes` 恒为 `strong/medium/cheap` 三档 | `doctor_command.py:182` 写死这三档 |
| UI 落点 | `ModelSection` 已在渲染这三档的就绪状态（provider + missing） | `SettingsPanel.tsx` ModelSection |
| 持久化 | `POST /api/studio/settings` **已是 patch 语义**（G8-a·1.2.104 改的） | `server.mjs`·非法值门口拒绝·旧单字段请求逐字兼容 |
| 冷/暖同源 | `lib/run-flags.mjs` 的既有模式；`warmRunParams(mode, strategy)` | 1.2.103/1.2.104 |
| worker | `studio_worker.py` **已在读** `request.get("model_name_overrides") or {}` | 刀一已接 |
| CLI | `--model-name TIER=MODEL`（可重复） | 刀一已接 |

⇒ **本刀是纯接线**，不需要任何运行时改动。

## 做什么

1. **UI**：ModelSection 里 G8-a 的 radiogroup **之下**，既有的每个 tier 行加一个模型名输入框。
   - **占位符 = 该 tier 当前解析到的模型**（`route.model`）⇒ 空输入框 = 「不钉，用配置的那个」，
     且用户**看得见**默认是什么。这比一个空框加一行说明更诚实。
   - 保存时机：**blur / Enter**（不是每次按键——每键一次 POST 会打爆 BFF 且抖动）。
2. **持久化**：settings 新字段 `modelNames: {tier: name}`。
   - 校验：tier 必须 ∈ 三档；值是字符串。**非法值门口拒绝**（照 G8-a 的既定口径）。
   - **空串 = 删除该档的钉死**（不是存一个空字符串）——否则 `{"strong": ""}` 会变成"钉一个叫空的模型"。
3. **BFF 冷/暖同源**（本刀的心脏，照 1.2.103/1.2.104 的既定模式）：
   - 冷路：`withModelNames(cmd, names)` 拼**多个** `--model-name TIER=MODEL`。
     ⚠️ 现有 `withRunFlag` 只加**一个** flag 且 `if (command.includes(flag)) return command` 会在第二次
     调用时**整个跳过** ⇒ **不能循环调用它**，要写一个能拼多值的助手。
   - 暖路：`warmRunParams(mode, strategy, names)` 加 `model_name_overrides` 字段。
   - **两路必须同源同输入**；`run-flags-unit.mjs` 的交叉一致性**扩到第三个选择**。

## 验收判据（DoD）

- [ ] `run-flags-unit.mjs`：冷路拼出的多个 `--model-name` 与暖路 `model_name_overrides` **逐档相等**，
      遍历 0/1/多档 + 非法档 + 空值。
- [ ] `settings-patch-smoke.mjs`：`modelNames` 的 patch 语义（不清零 permissionMode/modelStrategy）、
      非法 tier 拒收、**空串=删除**、被拒的保存不改状态。
- [ ] **真实用户路径探针**：Studio 填 `strong=X` → 发消息 → `run_config.json` 落
      `model_name_overrides: {"strong": "X"}`。**冷/暖各一次**，**暖路必须证明它真走了暖路**
      （结果相同 ≠ 走了那条路——冷回落会给出一模一样的 run_config·1.2.103 的坑）。
- [ ] DOM 驱动验控件（Browser pane 页面 0x0/hidden ⇒ 截图与 a11y 树不可用）。**视觉手感留用户目视**。
- [ ] vitest / tsc / eslint / smokes / 全量 pytest。

## 诚实边界

- **`model_calls.jsonl` 里"真用了 X"这一层，本刀验不到**：需要真凭证发真调用。零凭证探针只能证到
  `run_config` 落盘 + 单测证 client 的 `settings.model_name` 被换掉（刀一已证）。
  **如实记「未验到 model_calls 层及原因」，不声称**。
- 不做 provider 覆盖、不做 Studio 编辑本地路由文件——两者的理由见 S84，**本刀不重开**。
