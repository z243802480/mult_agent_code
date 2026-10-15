# S94 执行模型零工具调用修复（2026-10-15）

## 失败实证

S93 的 Studio 小任务完成规划后，执行模型两次只叙述、零工具调用，最终 `blocked`。S94 在同一隔离工作区、同一本机 provider 路由上先做只输出结构的探针：两次 `task_execution` 响应分别为 58 和 27 字符，均无法解析成 JSON，`finish_reason=stop`。探针没有保存或输出响应正文、工具参数或密钥值。这排除了“模型发了工具调用但解析器丢弃”这一猜测，确认是纯文本响应被循环当作无工具收尾。

## 修复

`model_driven_turn` 的 JSON 通道现在区分“合法完成回合”和“协议格式错误”：要求 `tool_calls` 为列表且 `done` 为布尔值。纯文本或缺少契约字段时，模型会收到明确的格式修正提示，说明此前没有工具执行，并在同一 `max_iterations` 保险丝内重试。不会从叙述猜动作，也不会绕开工具权限、写作用域或预算。持续不遵守格式时返回 `budget_exhausted`，不冒充完成。

## 真实复验

- Studio 用户入口的新会话，目标仍是给 `greet_cli.py` 增加 `--version`（输出 `0.1.0`）并补 pytest。运行 `run-20261015-0003` 从 16:33:30 到 16:37:25（约 3 分 55 秒）。
- 任务规划 1/1；Runtime 工具账本记录 **7 条成功调用**：`read_file` ×2、`write_file` ×2、`run_command` ×2、`run_tests` ×1。两份文件实际改动；`python greet_cli.py --version` 输出 `0.1.0`，运行中的 pytest 3/3 通过；独立重跑 pytest 亦为 3/3。
- `worker_results.jsonl` 为 `succeeded`，记录 2 份产物、3 条验证；`run.json` 为 `completed`，摘要写明可执行验证通过后自动接受。Studio 主线程显示 2 个修改文件、计划 1/1、验证完成和最终说明。此处的 Review/Accept 走现行 auto-accept 路径，没有人审点击。
- 仍观察到一段模型事件元数据原样混入主线程文本；它未改变本次执行结果，应单独复现并修 UI，勿和本刀的 JSON 协议修复混做。

## 测试与边界

- Red→Green：先用连续纯文本、缺字段对象、持续格式错误三种用例复现“零工具却被算完成”；修后 `test_model_driven_turn.py` 20/20。
- `test_execute_command.py` 41/41、`test_run_command.py` 35/35、文档契约 23/23；所改 Python 文件 Ruff 检查通过。以上测试未使用真实 provider；Studio 复验是本地真实 provider 路径。
- Git 已跟踪的 527 个 Python 文件 Ruff 全通过。直接 `ruff check .` 会额外扫到既有未跟踪的 `validation_multi_file_scope/`，其中两处原有 lint 错误使该命令失败；该目录未改、未入提交。本机 `mypy` 未安装，类型 ratchet 留待远端 Verify。
- GitHub keyed nightly 仍需双 key 才能运行，保持 `NOT RUN`；本刀没有配置 GitHub 密钥或提交本地临时工作区。
