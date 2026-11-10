# S105 执行上下文测量与安全去重

日期：2026-11-10。依据：总计划 §16.2、S104 六次成功采样、`benchmarks/reference_briefs/S105-execution-context-dedup.md`。目标是减少重复输入，同时保持模型驱动和原有安全、验证契约。

## 最终变更与边界

新增 execution_prompt_view，仅 ExecuteCommand 的模型输入使用。runtime_context 顶层和 context_package 中的 root_guidance，只有来源为 AGENTS.md、内容非空且被本轮实际系统提示中的项目指导完整覆盖时，才以 content_ref=system.project_guidance 替代重复正文。系统提示不变；原持久化对象不变；缺失系统指导、旧字符串形态、其他文件或未覆盖的尾部全部保留。原有 context_prompt_view 的通用行为不变，规划、评审、委派不改调用方式。

最初探索过裁剪有 path/hash 的 prompt_envelope.sections 和 capability_manifest，但回代码及实物发现其中还有网络策略、预算提示等独有内容，引用存在不等于语义重复。因此最终实现撤回该裁剪，完整保留审计投影、未知扩展、工具 schema、权限、作用域、验收、预算及失败观察。没有按题目、模型名或回复文本写规则。

## 可重复测量

隔离工作区使用 S104 已保存的 goal_spec/task_plan，状态重置为 ready，经实际 ExecuteCommand 装配，捕获客户端仅保存请求、返回空完成以截获输入，不访问 provider，不算模型验收。测量的是首个请求，而非后续完成闸轻推。用同一份旧请求重算新视图消除路径、时间与规划随机性；最终代码重新装配也得到相同字符数。

| 请求部分 | 原模型视图 | 最终模型视图 |
| --- | ---: | ---: |
| system 字符 | 10450 | 10450 |
| user JSON 字符（indent=2） | 72632 | 64346 |
| runtime_context 字符（默认 json.dumps，无缩进） | 42561 | 34275 |
| root_guidance 字符（同上） | 4225 | 82 |
| context_package 字符（同上） | 10150 | 6007 |
| prompt_envelope 字符（同上） | 8632 | 8632 |
| model_tool_surface 字符（同上） | 9323 | 9323 |

用户 JSON 减少 8286 字符 / 11.41%。这些是文本字符，不是 provider token 或计费量。两处指导正文各 4000 字符，系统提示已完整包含；不裁剪重复任务/验收和工具描述，避免把非完全相同的投影误当重复。

## 全部真跑结果

WSL Ubuntu / Python 3.12.3，既有本机路由，实际调用均为 MiniMax-M2.7。沿用 S104 同题、原始测试、auto/no-research/max-iterations=3、240 秒超时和独立检查，不修改权限门，不为获得通过追加同版本样本。每个工作区各有自己的 run-20261110-0001。

| 实现 | goal 秒 | 模型调用 | 输入 / 输出 token | 工具 / 失败 | 独立检查 | 闭环 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 探索版：同时裁 audit 与指导（已撤回） | 88.86 | 10 | 113239 / 4522 | 13 / 1 | 原测试及边界通过，哈希未变 | paused，未 Review/Accept |
| 最终版：仅去重指导 | 71.06 | 9 | 111888 / 3501 | 12 / 0 | 原测试 5/5 + 16 组及大整数，哈希未变 | completed → Review pass/1.00 → accepted |

探索版 apply_patch 用了不受支持的 Begin Patch 格式，返回 empty_patch，模型后续用其他文件工具修复成功。之后尝试 `rm -rf .pytest_cache __pycache__` 清理缓存，命中删除硬 guard、生成待决定并暂停；没有批准、重试绕过或将该样本计为成功。最终版是因安全语义复核收窄后的独立样本，不能用两者耗时或成败差异推出因果。

最终版首执行输入 17138 token，S104 旧版三例 18340–18716、新版三例 18689–19060。最终版 goal 总调用仍 9 次、71.06 秒处于 S104 六例范围内；规划和生成有随机性，未做同一请求的 provider 前后配对，因此这里只确认字符层面的确定减少，以及一个成功的真实闭环，**不声称稳定耗时或货币成本下降**。Review 无额外模型调用。cheap 路由的配置警告仍存在，但这些样本的实际模型账本没有 fake 调用，不能据此宣称所有路由均为真 provider。

原测试 SHA256：65c6e59291691b5cb872060ce6bca590ed8c94df425543adc9c439cd5ecde251。

## 验证与交接

- 执行/规划/重规划/评审/context_package/runtime_profile/MCP 相关回归 90 passed；模型驱动循环/能力环境/专家注册与去重边界 48 passed（部分基础测试重叠，不相加）。最终保留 audit 策略/预算及自定义 section 的断言另行复验。
- Ruff src/tests 通过；mypy ratchet 无新增（60 个既有错误，不改基线）；文档契约 23/23 与差异空白检查通过。
- 代码提交 dee309ae7ef7c4bc6da248c1c14519c78a3f2ce0 已推送；[Verify 42786745932](https://github.com/z243802480/mult_agent_code/actions/runs/42786745932) 的 Python 3.11、Python 3.13、Studio 三 job 全部 success，浏览器 UI 步骤实际执行通过。keyed nightly 仍 NOT RUN。本回执为后续仅文档更新，不改变已验证代码。

原始证据只在本机：WSL `~/.cache/asteria-s105/`（撤回的探索版）、`~/.cache/asteria-s105-final/`（最终版 samples.json、prompt-measurement.json、运行和独立验收日志）；捕获请求在 `~/.cache/asteria-s105-probe-1zqm1dzm/requests.json` 和 `~/.cache/asteria-s105-probe-e_3i97s_/requests.json`。没有把凭据、运行目录或既有未跟踪验证目录放入仓库。

ACTIVE_SLICE=S105，本刀最小实现、真实闭环与精确代码 SHA 的远端验证均完成。下一步在较实际的跨文件任务中检查工具格式契约和重复验证，先复现再决定是否修提示/工具反馈；本次 empty_patch 是候选证据，不据一次模型输出添加格式自动改写。独立 GLM 配额、大型仓库/数小时任务与广泛性能收益仍未验证。
