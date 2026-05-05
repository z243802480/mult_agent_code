# 开发环境与验证

本文档记录本地开发、模型配置、真实模型 smoke 和提交前检查。中文主文档是项目当前更详细的事实来源。

## 1. Python 环境

项目目标运行环境是 Python 3.11+。在仓库根目录执行命令前，建议设置：

```powershell
$env:PYTHONPATH = "src"
```

如使用虚拟环境，可安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

## 2. 常用命令

查看 CLI：

```powershell
python -m agent_runtime --help
```

初始化工作区：

```powershell
python -m agent_runtime init --root .
```

运行最小闭环：

```powershell
python -m agent_runtime run "实现一个本地 notes 模块" --root .
```

运行测试和静态检查：

```powershell
python -m pytest
ruff check .
mypy src
```

统一验证脚本：

```powershell
.\scripts\verify.ps1
```

## 3. 模型配置

默认 provider 是 MiniMax：

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

MiniMax key 有区域差异。运行时默认使用 `https://api.minimax.io/v1`；当 key 以 `sk-cp-` 开头时，会自动切换到中国区端点 `https://api.minimaxi.com/v1`。如需强制指定端点，可设置：

```powershell
$env:AGENT_MODEL_BASE_URL = "https://api.minimaxi.com/v1"
```

API key 只能通过进程环境变量、CI secret 或本机密钥管理注入。不要写入 `.env`、文档、测试夹具、日志或提交记录。

OpenAI-compatible provider：

```powershell
$env:AGENT_MODEL_PROVIDER = "openai-compatible"
$env:AGENT_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_MODEL_NAME = "<model name>"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

本地模型 provider：

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
```

分层路由示例：

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "minimax"
$env:AGENT_MODEL_STRONG_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_STRONG_NAME = "MiniMax-M2.7"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "ollama"
$env:AGENT_MODEL_MEDIUM_NAME = "qwen2.5-coder:7b"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"
```

未设置 tier 专属 provider 时，运行时会回退到全局 `AGENT_MODEL_PROVIDER`。

## 4. 真实模型 smoke

推荐直接使用真实模型 smoke 脚本。脚本会创建临时 workspace，执行 `/init`、`/model-check`
和最小 `/run`，并检查目标文件、session 日志、成本报告、模型调用、工具调用、review pass
状态，以及所有任务是否完成：

```powershell
python scripts/real_model_smoke.py
```

Windows 下也可以使用包装脚本：

```powershell
.\scripts\real_model_smoke.ps1
```

如果想固定输出目录或生成机器可读摘要：

```powershell
python scripts/real_model_smoke.py --root C:\temp\agent-real-smoke --summary-json C:\temp\agent-real-smoke-summary.json
```

如果网络链路偶发 TLS EOF、超时或 provider 抖动，可提高重试次数后重跑：

```powershell
$env:AGENT_MODEL_MAX_RETRIES = "5"
python scripts/real_model_smoke.py
```

脚本默认会在未显式设置 `AGENT_MODEL_MAX_RETRIES` 时为子进程使用 5 次模型重试，并在早期
provider 传输失败时重试整个 `/run`。如果需要调整完整 `/run` 尝试次数：

```powershell
python scripts/real_model_smoke.py --run-attempts 3 --model-max-retries 5
```

真实模型 smoke 的通过标准：

- `model-check` 能返回成功。
- `.agent/runs/<session_id>/final_report.md` 存在。
- run 状态为 `completed`。
- `eval_report.json` 的 overall status 为 `pass`。
- `task_plan.json` 中没有未完成或阻塞任务。
- 目标产物真实存在，并与用户目标一致。
- 失败、重试、工具调用和模型调用被记录到 `.agent/` 运行日志中。
- 仓库中不出现真实 API key。

## 5. 真实任务验收集

最小 smoke 通过后，可运行真实任务验收集：

```powershell
python scripts/real_model_acceptance.py --suite core
```

当前 `core` 套件包含：

- `file_smoke`：最小文件创建闭环。
- `password_cli`：生成单文件密码强度 CLI。
- `markdown_kb`：生成单文件 Markdown 索引/搜索工具。

也可以只跑单个场景：

```powershell
python scripts/real_model_acceptance.py --scenario password_cli
```

验收集默认要求真实 provider。只有测试 runner 本身时才使用：

```powershell
python scripts/real_model_acceptance.py --suite offline --allow-fake
```

`agent acceptance` 会把验收结果写入工作区下的 `.agent/acceptance/`：

- `latest_summary.json`：脚本原始机器可读摘要。
- `acceptance_report.json`：经过 schema 校验的 runtime 验收报告，包含 suite、场景、结果、失败摘要和输出尾部。

如果需要把失败验收纳入后续开发闭环，可以追加 `--promote-failures`：

```bash
python -m agent_runtime /acceptance --suite core --promote-failures
```

该选项会读取失败场景并在当前 session 的 `task_plan.json` 中生成 `ready` 修复任务，同时同步 `.agent/tasks/backlog.json`；如果当前没有 session，会明确失败，不会静默丢弃验收结果。
生成的任务会包含验收报告路径、summary JSON 路径、场景 workspace、smoke transcript、期望产物路径，以及可直接复现的 `agent /acceptance --scenario ...` 和底层脚本命令。
新生成的失败任务也会在 `.agent/memory/failures.jsonl` 中记录为 `failure_lesson`，后续 agent 上下文会自动读取这些经验。
每个 promoted failure 还会写入 `.agent/acceptance/failures/<scenario>.json` 作为结构化证据；`ContextLoader` 会把最近证据裁剪后注入后续 `/execute`、`/debug` 等 agent 上下文。
`/compact` 和 `/handoff` 也会携带最近 acceptance failure evidence，长任务交接后仍可定位失败场景、复现命令和 promoted repair task。
`agent sessions --context` 会显示 acceptance failure 数量和最新失败场景，便于恢复当前 session 时直接判断应执行 `/debug` 还是继续 `/execute`。
如果希望生成任务后立刻继续当前 session，可以显式追加 `--run-promoted`；默认不会自动触发模型执行，避免意外产生真实模型调用成本。
如果希望修复任务执行后自动复验本次新 promoted 的失败场景，可以显式追加 `--rerun-promoted`；该选项会隐式执行 promoted 任务，只复跑这些场景，并在 `acceptance_report.json` 的 `repair_closure` 中记录 `repair_run_id`、`rerun_ok`、`closed_failures` 和 `remaining_failures`。

这些产物用于后续把真实模型验收失败接入 memory、repair task 或 benchmark 回归。

## 6. 结构化输出容错

真实模型可能返回 `<think>`、markdown code fence、近似 JSON 或轻微字段漂移。运行时在模型边界做有限容错：

- 提取最后一个可解析 JSON 对象。
- 仅在整段响应是 code fence 时剥离 fence。
- 移除 `<think>...</think>` 推理块。
- 对 `GoalSpec`、`ExecutionAction`、`EvalReport` 做有边界的字段归一化。
- 所有持久化对象仍必须通过 schema 校验。

容错不是放宽数据模型。无法安全归一化的输出必须阻塞、记录原因，并进入修复或人工决策流程。

## 7. 验证产物

`agent run` 会在 `.agent/sessions/<session_id>/` 下写入：

- `goal_spec.json`
- `task_plan.json`
- `events.jsonl`
- `tool_calls.jsonl`
- `model_calls.jsonl`
- `cost_report.json`
- `review_report.md`
- `final_report.md`

提交代码前至少确认：

- 源码能通过 `.\scripts\verify.ps1`。
- 新行为有单元测试或集成测试。
- 涉及命令、模型或安全边界的修改有失败路径测试。
- 真实模型验证只记录示例 key 前缀，不记录真实 key。

## 8. ContextSnapshot 与 Handoff

长任务暂停、交接给后续 agent、准备压缩上下文，或进入需要用户决策的阶段前，应该运行：

```powershell
python -m agent_runtime /compact --root .
python -m agent_runtime /handoff --root . --to-role FutureRun
```

`ContextSnapshot` 必须保留可恢复现场，而不只是聊天摘要：

- 目标摘要和 Definition of Done。
- 已接受决策和待处理决策。
- 当前 run 状态、阶段和任务状态统计。
- 活跃任务、最近 artifact、修改文件、验证结果和失败证据。
- review/final report 摘要、开放风险和下一步行动。

`HandoffPackage` 会基于 snapshot 推荐下一条命令：

- 有 pending decision 时推荐 `decide --decision-id ...`。
- 有失败或 blocked task 时推荐 `debug`。
- 有 ready/in-progress task 时推荐 `execute`。
- 任务全部完成后推荐 `review`。
