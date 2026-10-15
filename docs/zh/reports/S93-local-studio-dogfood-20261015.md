# S93 本地 Studio 主路径 dogfood（2026-10-15）

## 实跑边界

- 独立临时工作区：`%TEMP%/asteria-s93-a6e5c4e7be264356aaad95bb7592c9eb`，内有 `greet_cli.py` 和原有的 1 条 pytest 测试；基线 `pytest` 通过。工作区和 `.asteria` 运行证据没有进入本仓库。
- 本地 Studio、warm worker、真实本机模型路由，从浏览器依次提交 Goal 和 `ask_everything` 权限确认。没有读取、记录或提交密钥值；GitHub keyed proof 仍为 `NOT RUN`。
- 目标：给 `greet_cli.py` 增加 `--version`（输出 `0.1.0`），补测试并运行 pytest。

## 观察和处理

1. **首次启动使用了尚未 `init` 的工作区**。warm worker 返回 `FileNotFoundError: .../.asteria/policies.json`，主线程却只显示“收尾时出了点问题”；Inspector 才能看到错误。原因是 warm control 的 `error` 字段被 server 丢弃。现已在结束事件中传递脱敏后的错误摘要，warm worker 意外退出也有明确说明。另一个分类错误把 `FileNotFoundError` 内的 `ENOTFOUND` 当作网络错误，现要求 `ENOTFOUND` 是独立词。`init` 后再跑；首次失败不记为模型或网络失败。
2. **初始化后真实运行**：Studio 接受 Goal，模型完成目标理解与一项任务规划；执行阶段强档模型调用 2 次均成功，却只输出“先读取文件”“现在修改文件”的叙述，`tool_calls.jsonl` 为 0 条，`worker_results.jsonl` 报“required verification was not provided / required changed artifact was not produced”。运行最终状态 `blocked`，原文件与测试未修改，pytest 未在运行中执行。Studio 结论明确说未完成，未把规划或模型调用成功冒充任务成功。
3. 同轮 UI 上，权限卡在确认后仍呈现“待批准”，尽管规划和执行已经继续；它与真实运行状态不一致，待下一刀用独立复现锁定，不在本刀顺手改动。

## 本刀修复与验收

- 最小修复：warm worker 错误进入主线程/Inspector；本地文件错误不再误报为模型网络故障。新增无 key 的集成 smoke，使用无效 provider 强制 warm worker 报错，并验证主线程和 Inspector 都收到原因；另断言真实 `ENOTFOUND` 仍归类为网络错误。
- 本地验证：`PYTHONPATH=src` 的 Studio hermetic smoke **41/41**；定向 warm worker smoke 通过；Studio lint 0 error（47 条既有 warning）、typecheck、所改文件 Prettier check 通过；文档契约 **23/23**。首次未设 `PYTHONPATH` 的整套运行 36/41，4 条因 Python 找不到本地包、1 条 `run-detail` 断言失败；按既有运行环境重跑 41/41，不把首轮失败抹掉。
- 切片结论：**S93 的真实用户路径已跑、证据已记录，但小任务没有完成；Review/Accept 无可验收改动，因此未执行。** 下一刀应聚焦模型叙述代替 JSON 工具调用：保存脱敏的响应形状、核对 `done/tool_calls` 解析与可用工具提示，再用最小回归复现并修复。不要从此次证据推断模型服务或 Studio 全链路通过。
