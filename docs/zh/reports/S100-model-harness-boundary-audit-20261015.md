# S100：模型能力补丁与驾驭边界审查

日期：2026-10-15。范围：S94、S97、S99 与执行命令网关。执行 brief：`benchmarks/reference_briefs/S100-model-harness-boundary-audit.md`。

## 判断口径

模型负责理解目标、选择工具、修复与收尾；harness 负责提供真实环境、工具 schema、权限、预算、观察与可核验结果。模型未遵守协议时可以给出有界的格式反馈；工具执行不能静默改写语义，验证状态不能靠输出文本猜测。此口径与 [Codex 的循环和环境上下文](https://openai.com/index/unrolling-the-codex-agent-loop/)、[OpenAI 对过密提示的反思](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)、[Claude 的工具契约](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)相符。它们说明的是机制，不构成对本仓库效果的自动证明。

| 现有机制 | 审查结论 | 处理 |
| --- | --- | --- |
| S94 JSON 回合格式错误 → 有界格式反馈 → 同一模型循环重试 | 通用传输协议；没有从叙述猜动作，也没有替模型选下一步 | 保留；仍需跨 provider eval 判断 JSON 与原生 tool use 的取舍 |
| S99 GoalSpec/Plan 的 OS 与“验收写可观察结果”提示 | 属于环境事实和任务契约引导；只给两阶段 OS 不完整 | 统一环境事实，并传给执行模型：OS、`run_command` shell、harness Python 路径 |
| 首轮零工具时断言目标文件“尚未产生”，提示直接 `write_file/edit_file` | 无工具记录只能说明本轮尚未观察到工具动作，不能证明文件不存在；模型的下一动作被代码越权指定 | 改为先检查已有状态、按需操作并验证；一次轻推保险丝保留 |
| Windows `ls -la <path>` → Python `Path.exists()`，返回 0 | **伪成功**：列目录被偷换成存在性检查，stdout 丢失，验证证据语义变了 | 删除命令重写，原样交 shell；失败照实回灌 |
| `python/python3` → `sys.executable`，并把 harness Python 目录放在 PATH 最前 | 静默换掉用户项目可能选择的解释器，可能在错误环境跑测试 | 删除命令重写，把 harness 目录改成 PATH 后备；将其路径作为环境事实提供给模型 |
| `python script.py` 非零退出但含 `Usage:` → `ok=True` | **伪成功**：内容启发式覆盖真实退出码 | 删除；仅真实退出码或显式 `expected_returncodes` 决定成功 |
| `run_tests` schema 允许模型传 `expected_returncodes` | 模型可以把失败码自行声明成“测试通过”，削弱验证工具语义 | `run_tests` 固定退出码 0 才通过；预期非零场景使用普通 `run_command` 并保留原始码 |
| 旧 `verification_command_normalizer.py` 按固定模式改写验证命令 | 全仓生产代码没有调用点，README 却仍描述它在运行；保留会造成路线和实现双重误导 | 删除未接线模块及其自证测试，README 改为真实执行契约 |
| S97 结尾模型的测试数正则与固定“思考前言”短语列表 | 有来源于真跑的证据卫生价值，但属语言表面启发式；可能漏掉别的表达，也可能拒绝有凭据的数字 | 本刀保留安全回退，列为后续治理债：提供带类型的测试数量与出处，再做多语言/多 provider eval 后替换短语规则；不凭直觉删除现有防误报层 |

## 改动与边界

命令网关现在执行原始命令，保留既有 ShellGuard、进程围栏、sandbox opt-in、超时和环境凭据清洗。`requested_command` 与 `command` 一致，默认成功仅取退出码 0；普通 `run_command` 调用者明确指定其他预期退出码时仍可验收该值，`run_tests` 则固定 0。GoalSpec、Plan、CoderAgent 用同一 `command_execution_context`，不写 `grep`/`ls` 黑名单。执行提示中“用户语言（Chinese）”的硬编码也已去掉。

保留的边界：本刀没有证明任何模型在所有 OS 上都会选择正确命令；没有配置远端 keyed nightly。工程目标是给模型真实能力描述、把真实错误返回给它、让验证结果不说谎。

## 后续验收与路线

定向测试覆盖原命令透传、`Usage:` 非零失败、`run_tests` 不接受预期非零码、项目 PATH 优先、三阶段环境上下文和零工具提示。相关短回归 **82 passed**，另有关键执行提示/PATH/返回码 3 项复验通过；`ruff check src tests` 通过。全工作区 `ruff check .` 被既有未跟踪验证目录中的 2 处 lint 问题挡住；`mypy src` 报 15 个未修改文件中的 60 个既有类型问题，均不计为本刀通过。较宽的相关范围首轮 **257 passed / 1 failed**：失败项是旧测试仍断言 `run_tests` 可把非零码算成功；按新契约更正后该工具组 **15 passed**。`main@647f66a` 的 [Verify run 38730482982](https://github.com/z243802480/mult_agent_code/actions/runs/38730482982) 三个 job（Studio 前端、Python 3.11、Python 3.13）均通过。下一批 Beta 任务应同时包含 Windows 与 Linux、文档与代码、至少两条 provider 路线；记录命令失败后的自修率和假绿率，再决定是否需要更强工具 schema 或按任务加载技能。避免给所有模型继续追加一次性提示规则。
