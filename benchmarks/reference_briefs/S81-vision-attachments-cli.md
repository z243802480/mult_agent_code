# S81 — G17 图片附件（第一刀：CLI 端到端）

Reference-first brief。授权：2026-07-17 用户"那就把 G17 做了吧，先 CLI 一刀"。
前置：1.2.95 撤回了 1.2.91 的"通道未就绪"搁置记录（活体探针证伪，见下）。

## 实证事实（活体探针·2026-07-17·非推断）

探针零仓库改动，只用 `os.environ` 覆盖 BASE_URL/NAME，结论：

1. **通道零改动即通**。`ChatMessage.content: str`（`models/base.py:10`）是**裸标注**——frozen
   dataclass 无 `__post_init__`、无 validator，出站路径（`to_payload:13-17` → `_payload` →
   `http_transport.py:45 json.dumps`）零 isinstance/assert。传 `content=[{"type":"text"...},
   {"type":"image_url"...}]` 直达 provider：**glm-4v-flash @ `/api/paas/v4` 对画着 `8264`
   的 PNG 正确返回 `8264`**（finish_reason=stop）。⇒ `openai_compatible.py` **一行不用改**。
2. **实配 coding 端点拒图**。同探针打 glm-5 @ `/api/coding/paas/v4` →
   `HTTP 400 code 1210: messages.content.type 不在合法取值范围 ['text']`。
   ⇒ **不能往默认档发图，必须有视觉档路由**。这是 G17 唯一的真架构缺口。

## 机制学习（不重造轮子）

- **Codex CLI / Claude Code / Cursor**：贴图/`--image` 的共同语义 = 图片作为**独立的多模态用户
  消息**进对话，不是把 base64 塞进正文；模型不支持时**明确拒绝并说明**，不做静默降级成"文件路径
  文本"（那会让模型假装看过图）。
- **能力路由**：主流把"视觉"当**模型能力维度**而非成本档。我们的 `MODEL_TIERS =
  ("strong","medium","cheap")` 是**成本轴**（`routing.py:8`），把 vision 塞进去会污染
  `tier_preference` 与 `_should_fallback_to_medium` 的回落语义。
- **现成先例**：`factory.py:60 create_recap_client` = 目的专用 client，**不进 tier 系统**，
  offline 时返回 `None` 让调用方诚实降级。视觉档照抄这个形状，不动成本轴。

## 交付（DoD）

1. `factory.py: create_vision_client(run_dir, validator, budget) -> ModelClient | None`
   —— 读 `AGENT_MODEL_VISION_*` 档，未配置返回 `None`（不猜、不回落到拒图的档）。
2. `base.py`：`content: str | list[dict]` 标注放宽（仅为过 mypy；运行时早已支持）。
3. `context_budget.py:130`：多模态分流。现状 `str(getattr(message,"content",""))` 会把 base64
   当正文按字符估（`:146-162` `ceil(other/4)`）→ 1MB 图 ≈350k tokens → ratio 1.75 → 假
   `budget_hard_stop`（`budget.py:270-281` → `supervised_goal_loop.py:66-80`）。
   **前瞻性隐患非当前活 bug**（今天无人往 content 写 list），但本刀引入 list ⇒ 必须同刀修。
4. `chat_command.py`：`attachments: list[Path] | None` 形参；图片消息插在 json.dumps 信封
   **之前**（避开 `fake.py:149/237/293/339` 与 `acceptance/runtime_os_scenarios.py:28,315`
   的 `messages[-1].content` 是 JSON 串假设）；未配视觉档 → **明确报错说明怎么配**，不静默。
5. `cli.py`：`asteria chat --image <path>`（可重复）。
6. **验收 = 真跑**：`asteria chat --image <画着已知数字的图> "这图里写的什么数字"` 返回该数字。
   非 mock、非单测。外加单测锁：未配置档的诚实报错、信封顺序、多模态 token 估算。

## 非目标（本刀不做）

- 前端 onPaste / 上传端点 / 引用渲染（约为后端 10 倍工作量，下一刀）。
- 能力矩阵 / 自动能力路由 / `DefaultModelRoute` 加能力维度 —— 那是成熟化，要单独 ADR。
- 视觉档进 `MODEL_TIERS` 成本轴（见上，会污染回落语义）。
- 不碰 `openai_compatible.py`（探针证明零改动即通；另一会话正在改该文件）。
- 不碰 `execute_command.py` / `run_command.py`（DO_NOT_TOUCH），本刀只走 chat 路径。

---

# 刀二 — Studio 前端粘贴（2026-07-17 续写）

授权：用户"那就把 G17 做了吧，先 CLI 一刀"→ 刀一已落（1.2.96），刀二为其自然续。

## 测绘结论（读码所得·非推断）

- **Studio 的 chat 不走 CLI**：`chat-answer.mjs:270-294` 把 `{question, history}` 打成 base64 塞进
  `ASTERIA_STUDIO_CHAT_PAYLOAD` 环境变量，内联 python 直接 `import ChatCommand`。
  ⇒ 附件只需在 payload 里加一个 `attachments: [路径]`，**绕开** `chat-routes.mjs:63`
  `redactText(String(body?.message))` 那个有损漏斗，也绕开 `server.mjs:2063` 的 64KB JSON 闸
  （payload 里只有短路径，图片本体走独立上传端点）。
- **存储落点已被证成立**：`workspace-paths.mjs:11-20` `isSafeWorkspacePath` **不拦 `.asteria/`**；
  `MemoryPanel.tsx:87-88` 已有直读 `.asteria/` 的投产先例；`fileChanges.ts:63-66` 有意把 `.asteria/`
  排除出 Keep/Revert（正是附件想要的：不该出现在改动面板里）。
- **回显零新通道**：`preview-server.mjs` 随 boot 起在 port+1，`:119` 无扩展名白名单、`:136` 二进制读、
  `:24-32` 完整图片 MIME 表、`:169-174` 正确 content-type ⇒ 直接当图片 CDN 用。
- **上传原语已有**：`server.mjs:2080 readRequestBodyRaw`（25MB）。

## 交付（DoD）

1. BFF `POST /api/studio/attachments?session=&name=` 收原始二进制 → 按内容 hash 存
   `.asteria/attachments/<session>/<hash>.<ext>` → 返回 workspace 相对路径。
   守卫：仅图片扩展名 + 体积上限 + session id 校验 + 内容嗅探（不信 name）。
2. `Composer` `onPaste` 抓剪贴板图片 → 上传 → 附件 chip（可删）；发送时随 body 带路径。
3. `chat-routes.submitUserGoal` 读 `body.attachments` → 逐条 `isSafeWorkspacePath` 校验 →
   透传到 `chat-answer` → payload → `ChatCommand(attachments=...)`。
4. 回显：`user_message` 事件带附件路径，主线程渲染缩略图（经 preview-server）。
5. 验收 = **真栈**：Studio 里粘一张画着已知数字的图 + 提问 → 模型答出该数字。

## 非目标 / 已知边界（刀二不做）

- **纯图无文字发送**：`chat-routes.mjs:68` `if (!goal)` 挡空消息。允许空问题需给模型一个
  编造的默认提问（"描述这张图"）——那是替用户说话，不做。要求配文字，诚实记录此差距。
- 拖拽上传 / 文件选择按钮（粘贴是主流主路径，先做这条）。
- 非图片附件（PDF/文本）——后端 `ATTACHMENT_MIME_TYPES` 只认图片。
- 附件清理策略（与 G7 快照同理，本地磁盘，有意留白）。

## 未验证 / 风险

- minimax 视觉能力未测；连续同角色消息 vs 单条 parts 数组的兼容性未测（本刀用**独立图片消息**，
  若 provider 拒连续 user 消息则改单条 parts 数组 + 同步改 fake.py 的 `messages[-1]` 假设）。
- `redactText`（BFF 侧）可能损坏 base64 —— 本刀不经 BFF，下一刀再验。
