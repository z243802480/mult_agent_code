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

先做 provider 健康检查：

```powershell
python -m agent_runtime model-check --root .
```

再用临时目录跑一个端到端最小任务，避免污染当前仓库：

```powershell
$root = Join-Path $env:TEMP ("agent-real-e2e-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $root | Out-Null
python -m agent_runtime run "Create a local file hello_runtime.txt containing one line: real model smoke ok" --root $root --max-iterations 3 --max-tasks-per-iteration 1
```

如果网络链路偶发 TLS EOF、超时或 provider 抖动，可提高重试次数后从 session 继续：

```powershell
$env:AGENT_MODEL_MAX_RETRIES = "5"
python -m agent_runtime review --root $root --session-id <session_id>
python -m agent_runtime resume --root $root --session-id <session_id>
```

真实模型 smoke 的通过标准：

- `model-check` 能返回成功。
- `.agent/sessions/<session_id>/final_report.md` 存在。
- 目标产物真实存在，并与用户目标一致。
- 失败、重试、工具调用和模型调用被记录到 `.agent/` 运行日志中。
- 仓库中不出现真实 API key。

## 5. 结构化输出容错

真实模型可能返回 `<think>`、markdown code fence、近似 JSON 或轻微字段漂移。运行时在模型边界做有限容错：

- 提取最后一个可解析 JSON 对象。
- 仅在整段响应是 code fence 时剥离 fence。
- 移除 `<think>...</think>` 推理块。
- 对 `GoalSpec`、`ExecutionAction`、`EvalReport` 做有边界的字段归一化。
- 所有持久化对象仍必须通过 schema 校验。

容错不是放宽数据模型。无法安全归一化的输出必须阻塞、记录原因，并进入修复或人工决策流程。

## 6. 验证产物

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
