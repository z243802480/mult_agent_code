# 真实模型验收

本文档记录真实模型 provider 的手动验收和定期验收流程。它和离线验证分开维护，因为真实验收会消耗 API 调用额度。

## 套件

- `smoke`：最小文件创建闭环。
- `core`：`file_smoke`、`password_cli`、`markdown_kb`。
- `advanced`：失败测试修复和决策点处理。
- `nightly`：所有不依赖用户数据、适合定期运行的真实验收场景。
- `offline`：只用于 fake provider 的脚本自身覆盖。

## 推荐命令

先跑 provider 健康检查：

```powershell
python -m agent_runtime /model-check --root .
```

运行最小真实模型闭环：

```powershell
python scripts/real_model_smoke.py --summary-json .agent/verification/real_model_smoke.json
```

运行当前真实任务验收集：

```powershell
python scripts/real_model_acceptance.py --suite core --summary-json .agent/verification/real_model_acceptance_core.json
```

额度允许时运行更完整的 nightly 验收：

```powershell
python scripts/real_model_acceptance.py --suite nightly --summary-json .agent/verification/real_model_acceptance_nightly.json
```

持久化可对比历史：

```powershell
python scripts/real_model_acceptance.py --suite core --summary-json .agent/verification/real_model_acceptance_core.json --history-jsonl .agent/verification/real_model_acceptance_history.jsonl
```

## 摘要指标

`real_model_smoke.py` 会写入：

- `duration_seconds`
- `diagnostics.run_status`
- `diagnostics.review_status`
- `diagnostics.review_score`
- `diagnostics.task_status_counts`
- `diagnostics.model_calls`
- `diagnostics.tool_calls`
- `diagnostics.estimated_input_tokens`
- `diagnostics.estimated_output_tokens`
- `diagnostics.repair_attempts`
- `diagnostics.context_compactions`

`real_model_acceptance.py` 会把这些成本和稳定性指标按场景聚合。
提供 `--history-jsonl` 时，脚本会把每次 summary 追加到 JSONL 历史，并在当前 summary 中写入
`trend.previous` 和数值 delta，覆盖通过/失败数量、耗时、模型/工具调用、token 估算、修复次数和
context compaction 次数。runtime 的 `agent /acceptance` 默认会把历史写入
`.agent/acceptance/history.jsonl`。

查看 runtime 工作区历史：

```powershell
python -m agent_runtime /acceptance-history --root . --limit 5
```

查看脚本级自定义历史文件：

```powershell
python -m agent_runtime /acceptance-history --root . --history-jsonl .agent/verification/real_model_acceptance_history.jsonl
```

## 通过标准

一个场景只有满足以下条件才算通过：

- `/model-check` 成功。
- 期望产物存在，并包含期望文本。
- 必要运行产物存在且非空。
- `run.json` 状态为 `completed`。
- `eval_report.json` 的 overall status 为 `pass`。
- 当前有效任务均为 done；`discarded` 只允许作为被 replan 替代的历史修复记录。
- 成本计数和 JSONL 日志数量一致。

真实验收失败不应被忽略，应通过 `agent /acceptance --promote-failures` 纳入修复闭环。
