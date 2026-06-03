# Asteria Studio 产品设计

本文合并原 `Asteria Studio 产品与架构.md`、`Asteria Studio 用户侧工程设计哲学.md` 和 `Asteria Studio 真实任务基准.md`。Studio 是 Asteria 的独立产品交互面，不是新的执行内核、命令包装器或后台 dashboard。

当前后端 runtime 优先级仍高于 Studio，但 Studio 的长期方向成立：用户在一个本地 workspace 中输入目标，看到可理解的进展、权限请求、文件变化、验证结果和最终交付；runtime 继续负责权限、预算、schema、证据、恢复和 gate。

Studio 的 session、context、主会话过程展示和 Inspector 诊断层必须遵守 [Studio 会话与上下文设计准则.md](./Studio%20会话与上下文设计准则.md)。新增 UI 前先判断它属于主会话叙事、用户动作入口，还是 Inspector 证据层；不得把 Studio 重新做成固定 runtime dashboard。

## 1. 产品定位

Studio 面向三类场景：

- 普通用户智能体工作区：输入 Goal / Plan / Ask，看到目标理解、计划、执行、权限、文件变化、验证和结果。
- Project / Workspace 管理：最近项目、打开本地文件夹、workspace 绑定的 session/run/evidence/file/Git/plugin/skills/settings。
- 开发者 dogfooding / Ops：诊断 gate、route、validation、worker evidence、promotion 风险和证据包。

Studio 不负责：

- 绕过 runtime policy 执行任务。
- 保存或显示 API key。
- 直接修改 `.asteria/` schema 对象。
- 取代 CLI / JSON 控制面。
- 提供 unrestricted agent chatroom。
- 把默认首页做成营销式 dashboard 或 maintainer 控制台。

核心原则：

```text
Product Workspace 负责用户心流。
Ops / Debug Console 负责 runtime 诊断。
两者消费同一套 runtime evidence，但默认不混在一个主线程里。
```

## 2. 默认信息架构

默认首页是 Product Workspace：

- Left Sidebar：Projects / Workspaces、Sessions、Search、Settings。
- Main Thread：用户消息、assistant 进展、权限卡、文件变化、最终结果。
- Composer：自然语言输入，显式或自动选择 Goal / Plan / Ask。
- Inspector：选中事件详情、命令输出、文件/diff/artifact、Git、token/cost、evidence refs。

Ops / Debug Console 独立承载：

- gate/status/review/accept/evidence/model route/cost/policy。
- Inspector / Evidence Explorer / raw artifacts。
- Debug Agent 对 backend state 的解释。

默认主线程只展示用户能理解的进展，不展示裸 stdout、schema 噪声、run id 列表或 maintainer 命令。

## 3. 前台事件模型

Studio 不应解析 stdout 来猜结果。runtime 应主动产出 `user_progress.jsonl`，Studio 把它映射成用户任务进展。

主线程阶段：

```text
理解目标 -> 制定计划 -> 执行/生成 -> 核对验证 -> 结果 -> 下一步
```

内部细节进入 Inspector：

```text
runtime command
stdout/stderr
raw tool events
schema/evidence refs
model/route/token telemetry
```

前台事件至少包含：

```json
{
  "event_id": "evt-...",
  "session_id": "studio-session-...",
  "run_id": "run-...",
  "type": "assistant_delta | tool_start | permission_request | file_changed | final_answer | error",
  "status": "queued | running | waiting_user | completed | failed",
  "title": "Planning route",
  "summary": "Reading workspace instructions and building a task plan.",
  "artifact_refs": [],
  "evidence_refs": []
}
```

正式回复必须来自 runtime 结果、review report 或真实模型。如果暂时没有真实模型结果，界面必须明确显示“正在规划 / 等待模型 / 等待权限”，不能用规则回复冒充执行完成。

## 4. 用户可见模式

用户直接可见的模式：

- `Goal`：执行目标，允许在权限策略内修改文件、运行验证和生成交付物。
- `Plan`：只读分析，不修改用户业务文件。
- `Ask`：轻量问答，默认不进入长任务执行。

自动路由建议：

- ordinary Q&A -> Ask。
- progress / status / next-step question -> Ask + 挂载 active long-task status。
- read-only planning / comparison / evaluation -> Plan。
- workspace-changing task -> Goal，并按风险显示权限卡。
- large ambiguous request -> Plan first，再让用户确认优先级。
- backend / route / evidence / trace question -> Ops / Debug Console。

每次自动路由应形成 `IntentRoute` 记录，至少包含 intent、target_mode、confidence、permission_pressure、risk_reason 和 recommended_next_action。

## 5. 权限、文件和 Git

权限卡必须说明：

- 要运行什么命令。
- 会读哪些范围。
- 会写哪些范围。
- 是否联网。
- 预计 token/cost。
- 风险等级。
- 用户选择：允许一次、本会话允许同类操作、拒绝、修改目标。

文件体验围绕“本次任务产物”，而不是全局文件列表：

- 本次任务新增/修改/删除文件。
- diff 和 artifact 预览。
- git status。
- candidate workspace、promotion queue、approve/reject/discard/retry。
- 主工作区是否被污染。

所有写入、回滚、commit、promotion 操作必须走 runtime policy 和权限记录。

## 6. 本地 API Adapter

Studio 后端只监听 localhost，默认端口 `8787`。它优先调用 runtime CLI 的 `--json` 输出；没有 JSON 输出时读取 workspace 内 `.asteria/` 的 JSON/JSONL evidence。

API adapter 规则：

- 启动时绑定一个 workspace；run/session/evidence/file preview 默认从该 workspace 读取。
- 全局 recent workspace、current workspace、模型 route 是否存在和 UI 偏好可读取用户目录摘要。
- API response 必须脱敏。
- 不读取 protected paths。
- 不把 API key、route local 文件或 `.env` 发送给前端。
- 文件预览只允许安全白名单路径和小文本文件。

Studio P0 不让用户直接选择 `execute-one`、`review`、`promotions`、`gate-status`、`validation` 等 runtime 命令；这些可以在内部映射为受控 action。

## 7. 安全边界

Studio 必须默认排除：

- `.env`、`.env.*`
- `secrets/`
- `.git/`
- `*.pem`、`*.key`
- `model.routes.local.ps1`
- `model.routes.local.json`
- 任意包含 `api_key`、`token`、`authorization`、`password`、`secret` 的字段值

前端只显示 key 是否 present、provider/model/base_url 摘要、route latency 和调用结果。

## 8. 真实任务基准

Studio 进入用户内测前必须证明它不是后台日志换皮。基准清单位于：

```text
benchmarks/studio_user_tasks.json
```

第一批任务覆盖：

- 通用规划：青岛三日旅行计划。
- 小代码任务：给 CLI 增加参数并补测试。
- 分析诊断：分析失败日志并给修复建议。
- 文档综合：整理零散需求为一页 PRD。
- 连续任务：继续上次未完成任务。

运行命令：

```bash
python -m asteria_runtime studio-benchmark --root .
python -m asteria_runtime studio-benchmark --root . --json
python -m asteria_runtime studio-benchmark --root . --session-id session-xxx
```

最低门槛：

- `studio-benchmark` 分数达到 0.80。
- 五个基准任务都用真实 UI 跑过并保留事件。
- 至少一个通用任务和一个代码任务使用真实 provider。
- Workspace Switcher 跑通 Recent、Open folder、切换已有项目、新建 session、继续旧 session。
- 三种权限模式至少各跑通一个任务片段，并能在 Inspector 看到 permission evidence。
- 主线程不出现大段裸 stdout。
- 失败任务必须有可读失败原因和下一步。

当前基准是准入诊断，不是美观评分；真实用户内测还需要 Playwright 截图和文件/Git/权限路径覆盖。

## 9. 下一步实现

1. 用五个基准任务跑真实会话，补齐 capability、权限、文件预览和继续迭代证据。
2. 将实时订阅从轮询升级为 SSE/WebSocket。
3. 在基准报告中增加 Workspace switcher、权限模式、Inspector 分区和文件/Git 视图覆盖检查。
4. 保持 Product Workspace 与 Ops / Debug Console 分离，避免默认首页退回后台 dashboard。
