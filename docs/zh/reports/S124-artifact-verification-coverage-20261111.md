# S124：让文档实例进入真实验证

2026-11-11；[brief](../../../benchmarks/reference_briefs/S124-artifact-verification-coverage.md)。承接 S123 的实际覆盖缺口：项目测试通过、文档声明输出错误、默认评审未发现。S123 原初轮拒收及外部反馈阶段接受仍分别保留。

## 结论

**工程改动已落地，单次新文档审计目标通过独立验收及正式 Review→Accept。** 执行器为 `27135b3c0fa21d14e56d0298127b899fc9567df7`。这次不提供错误位置、正确计数或现成文档检查器；模型自行运行例子、比较声明、修正文档，再对两个例子断言。不是上一轮收到 Expected/Got 后的反馈修复，也不是旧版本成对因果实验。

实际 **217.76 秒、17 次真实 MiniMax-M2.7 调用、54 条工具记录/观察**；输入 **451,802**、输出 **13,105** tokens，与账本逐项相符。独立标准库 doctest **9 次尝试/0 失败**、项目 **271 passed / 1 skipped**；只改两份许可文档，源代码、旧测试、配置和 S123 原源码/运行状态不改。正式 Review pass/1.00、Accept accepted，没有新增模型调用。

## 通用改动与边界

- GoalSpec、PlanAgent 与 AgentHarness 执行纪律共享产物验证引导：检查要对应实际声明；可执行例子核对前置条件、调用和输出，普通文字按适当证据检查。保留项目/用户必需检查，补充检查只能在既有权限内按实际工具选择。不给某个仓库、模型或错误词加分支。
- 执行纪律不再把模型限定为“只能运行已有契约命令”。它仍须完成必需命令，不能靠补充命令替换失败检查、擅自安装或在许可外写检查脚本；真正受阻时按既有 replan/ask 处理。
- Review 明确命令通过率不等于产物/需求覆盖率，文件存在和读回不等于语义已验证。确定性及稀疏评审不再把任务完成率填成 requirement_coverage，改为 coverage=null、task_completion_rate 单列；模型明确返回的覆盖判断保留。未知覆盖不新增完成闸，恢复分类沿用任务完成信号；实际 score/status、预算和工具权限不提高。
- 没有新增自动 doctest 机制、第二评审运行时或编排 Wave，没有改 execute/run/acceptance 栈，也没有改变 JSON schema 的严格程度。

参考的是 [Claude Code 的可运行检查与真实输出反馈](https://code.claude.com/docs/en/best-practices#give-claude-a-check-to-run)、[Codex-rs 从具体变更开始验证的提示](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md#validating-your-work)。采用通用引导加原有工程边界，不复制专有实现。

## 新目标的登记与过程

从 S123 原初轮源码复制不带 `.asteria` 的全新工作区，原错误保留；目标仅审核修正 `TinyDB.apply_batch` 的两份文档，保持标题和无关内容、全部实现/测试/配置，不新增文件。模型可读本地实现和公约，不可访问 evaluator、执行器、其它实验、网络或秘密。

调用前提交产品与输入 `27135b3`；公开项目命令经真实 RunCommandTool 在 Runtime 相同父环境通过。显式 `pythonpath=.`，未给模型偷偷注入项目 PYTHONPATH；Python `-c` 在工作区根目录正常导入源码。evaluator-only oracle 初始 5 尝试/1 失败；S123 已修文档对照为绿，检查器不放模型工作区。默认实际 profile=session_agent，未强制档位，原权限/预算不提高，外部上限 900 秒未触发。

输入 SHA256：goal `9606adaeb0051dfa42f6bcdd29168fd96aab4863e568a3a81c210717ad720e69`；oracle `d0106a6830f897cd390aa42f9c57c078bf7db8c90e568c8a9c905fab8e136613`。源码与导出的 src/schemas 都有完整哈希冻结。

实际模型规划把“可执行例子的前置条件、调用及声明结果经本地源码核验”列为验收标准，并保留 focused/full pytest 命令。模型先执行 usage 中的原操作序列，工具输出 inserted=2，与文档的 1 不一致；随后只修正这个数字，并给 API 节新增自包含的 put/replace/remove 例子。修后用 inline Python 分别断言两个例子的实际结果，再跑原测试。没有收到中途解题提示或人工修改。

54 条工具/54 条观察 ID 一一对应且唯一：19 read_file、9 todo_write、8 search_text、5 run_tests、7 apply_patch、3 run_command、2 diff_workspace、1 list_files。7 个失败为 3 个 patch 格式、2 个 patch 上下文及 2 个 diff 调用；无 denied。模型自行调整继续，未放宽权限。全部路径/命令、7 次 patch 目标和完整 diff 经人工检查，无 evaluator/执行器/安装包源码/秘密/网络访问。

独立验收直接执行两份文档中的实际例子，9/9；不是仅验证模型重写的 inline 断言。usage 改 1 行、API 新增 15 行，其它文件全哈希未变。正式评审后源码哈希不变、账本前缀不变，最终计量精确对齐，coverage 保持未知而任务完成率为 1.0。

## 工程验证与证据位置

Windows 冻结版本完整回归 **1785 passed / 3 skipped / 42 deselected**（549.16 秒）；WSL 相关 **111** 过，Ruff（src/tests）、类型债 ratchet（60 known，无新增）、五个离线基准通过，ring fake 档仅 PLUMBING OK，不冒充恢复证明。新 oracle 回归涵盖真实错误输出、正确输出、缺失 usage 例子以及可只含文字的 API 节。

首轮 Windows 全量为 1780 passed / 1 failed / 3 skipped：启动时一个临时断言误把模型明确提供的 coverage 也当作未知，加载后才修正；修正后的 Review 相关 24 项过，WSL 111 过。随后在已冻结提交上完整重跑，1785 项全过；以上首轮失败不记为通过。

产品提交的 [Verify 43040328283](https://github.com/z243802480/mult_agent_code/actions/runs/43040328283)：Python 3.11/3.13 完整 job 通过；Studio **失败**，公开 failure annotation 确认浏览器系统依赖安装报 Temporary failure resolving azure.archive.ubuntu.com，UI skipped。S123 的 DNS 失败记录仍保留，未改 workflow 或跳过 UI。

WSL 工作区：`~/.cache/asteria-workspaces/s124-doc-audit`；运行：`run-20261111-0001`；执行器：`~/.cache/asteria-runtimes/s124-27135b3`；完整登记、预检、原/新哈希、工具审计、独立检查及正式接受：`~/.cache/asteria-evaluations/s124-doc-coverage-20261111`。同名 run 不代表与 S123 同一个运行根目录。

## 本次发现与下一项

**S125：明确编辑边界在 session_agent 中的传递。** 实际 GoalSpec 正确保留“仅改两份文档”，原模型任务的 expected_changed_files 也只有两份；但 `RequirementPlanner._widen_session_agent_write_surface` 后处理扩大到 `docs/`、`tests/`、`tinydb/` 与 implementation artifact。用真实任务的 path_in_write_scope 探针确认代码与测试路径也被允许。模型本次实际没有越界，因此不虚构一次越界写，但不能称工程边界已落实。证据为本次审计 `scope-probe.json`。

下一项先核对显式编辑边界与开放目标的责任，保留自主检查/上下文探索，以通用结构化契约传递用户明确授权并让规划/工具层尊重它；不从关键词/文件数猜权限，不给 TinyDB 特判。本刀不夹带该修复。

本次仅证明单 provider 的约 3 分 38 秒文档审计闭环。没有旧/新版本成对对照，不证明普遍可靠性、稳定降本或小时级自治；独立 provider 与 keyed proof 仍未运行。
