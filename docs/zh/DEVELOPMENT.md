# 开发环境与验证

## 1. Python 环境

项目目标运行环境是 Python 3.11+。在仓库根目录执行命令前，建议设置：

```powershell
$env:PYTHONPATH = "src"
```

如果使用虚拟环境，可安装开发依赖：

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

检查模型配置：

```powershell
python -m agent_runtime model-check --root .
python -m agent_runtime model-check --root . --skip-call
```

`--skip-call` 只检查本地环境变量；不带该参数时会向模型发送一次很小的 JSON 健康检查请求。

运行最小闭环：

```powershell
python -m agent_runtime run "实现一个本地 notes 模块" --root .
```

运行测试和静态检查：

```powershell
python -m pytest
python -m compileall -q src tests
ruff check .
mypy src
```

## 3. 模型配置

默认 provider 是 MiniMax：

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

也可以使用 OpenAI-compatible provider：

```powershell
$env:AGENT_MODEL_PROVIDER = "openai-compatible"
$env:AGENT_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_MODEL_NAME = "<model name>"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

## 4. 验证产物

`agent run` 会在 `.agent/runs/<run_id>/` 下写入：

- `goal_spec.json`
- `task_plan.json`
- `events.jsonl`
- `tool_calls.jsonl`
- `model_calls.jsonl`
- `cost_report.json`
- `review_report.md`
- `final_report.md`

提交代码前至少确认：

- 源码能通过 `python -m compileall -q src tests`。
- 新行为有单元测试或集成测试。
- 涉及命令、模型或安全边界的修改有失败路径测试。
