# Asteria Studio 开发计划

## 1. P0 目标

P0 目标是让开发者在干净环境内测前后，能用本地 Web 控制面查看 Asteria 的真实状态，并能用一个轻量交互层触发安全 runtime 动作。

完成定义：

- `studio/` 可以独立安装依赖、启动和 build。
- UI 能显示 overview、doctor、package-check、gate-status。
- UI 能列出 runs 并查看 run detail。
- UI 能展示模型 route 聚合指标。
- UI 有 Agent Workspace，用户可以在同一处对话、确认权限、触发动作、查看反馈和预览产物。
- UI 能保存本地 conversation 历史，并用当前 gate/run/model evidence 回答状态类问题。
- UI 能触发 `evidence-bundle` 导出。
- 所有数据来自 runtime CLI 或 `.asteria/` evidence。
- 不读取、不显示、不导出 API key。

## 2. P0 页面

### 2.1 Agent Workspace

首屏主入口：

- 对话流。
- 权限/待确认动作。
- 自然语言输入。
- 常用动作按钮。
- 命令预览。
- 安全动作执行。
- 执行后刷新 dashboard。
- 文件/证据/报告预览。

第一批动作：

```text
初始化工作区          init --profile auto
从目标生成计划        plan <goal>
受限真实任务运行      run --max-iterations 2 --max-tasks-per-iteration 1 --no-research <goal>
执行一个 ready task   execute --max-tasks 1
审查 run              review
恢复运行              resume --max-iterations 2 --max-tasks-per-iteration 1
查看待决策项          decide --list-pending
查看 promotion queue  promotions list --json
查看当前门禁        gate-status --json
运行灰度入口检查    gate --json
准备 gray dry-run   gray --json
检查本机环境        doctor --json
检查安装包          package-check --json
导出证据包          evidence-bundle --json
真实任务运行        仅建议命令，等待 policy/approval 产品化
```

### 2.2 Overview

显示：

- workspace path。
- release stage。
- rollout state。
- release_ready。
- blocking_reason。
- real_model_gate / gray_suite / core_acceptance 状态。
- next_actions。

### 2.3 Environment

显示：

- package-check status。
- doctor status。
- strong / medium / cheap route configured。
- API key present。
- streaming enabled。
- git / sandbox status。

### 2.4 Model Routes

显示：

- provider / model / purpose / tier。
- total calls。
- success rate。
- failure count。
- streaming failed count。
- first chunk p50/p95。
- duration p50/p95。

### 2.5 Runs / Run Detail

显示：

- run_id、status、current_phase、summary。
- event timeline。
- model calls tail。
- task execution evidence tail。
- worker results tail。
- validation results tail。

### 2.6 Conversation

显示：

- 本地 conversation 列表。
- 当前对话消息历史。
- Studio 基于当前 evidence 的规则化回复。
- 回复关联的 evidence refs。

P0 不调用模型；它只解释现有 runtime 证据。P1 再评估是否通过 runtime policy 接入真实模型。

## 3. API

第一版 API：

```text
GET  /api/overview
GET  /api/doctor
GET  /api/package-check
GET  /api/gate-status
GET  /api/runs
GET  /api/runs/:runId
GET  /api/model-routes
GET  /api/workspace-files
GET  /api/workbench-actions
GET  /api/agent-actions
GET  /api/conversations
GET  /api/conversations/:conversationId
POST /api/workspace-files/preview
POST /api/workbench-actions
POST /api/agent-actions
POST /api/conversations
POST /api/evidence-bundle
```

Conversation 存储：

```text
.asteria/studio/conversations.jsonl
```

## 4. 验证

本地验证：

```powershell
cd studio
npm install
npm run typecheck
npm run build
npm run server -- --workspace F:\mult_agent_code
```

Runtime 验证仍然在仓库根目录运行：

```powershell
ruff check .
mypy src
python -m pytest tests -q
```

## 5. 后续 P1

- 长任务执行队列与 heartbeat。
- run/gray/core 的实时 timeline。
- promotion queue 可视化 approve/reject/discard。
- failed evidence 到 debug/replan 的操作建议。
- Conversation 绑定具体 run、gate、action 和文件 diff，成为操作历史索引，而不是单独聊天框。
