# S104：成功任务成对成本采样

日期：2026-11-10。预注册方案：`benchmarks/reference_briefs/S104-successful-task-cost-sampling.md`。

## 任务、执行与判据

对照代码固定为 `48c08a4` / `37516da` 的 Git 追踪快照，两份代码均在 WSL Linux 用户缓存内，使用同一 Python 3.12.3 venv、同一本机路由与普通 goal 入口。按 A/B、B/A、A/B 顺序完成六次，每次独立新工作区，无失败后追加挑选或重跑。执行模型账本六次均只有 MiniMax-M2.7，没有 fake 或其他 provider 调用；显式 Review 没有追加模型调用。

固定缺陷 `calc.py`：`add(a, b)` 错误返回 `a - b`。原测试五组参数：(2,3,5)、(-4,7,3)、(0,0,0)、(8,-3,5)、(0.5,1.25,1.75)。README 只要求修复该函数、无依赖/额外 API/功能，不得改测试，明确无 Git 仓库。原测试 SHA256 六次均为 `65c6e59291691b5cb872060ce6bca590ed8c94df425543adc9c439cd5ecde251`，修复前均非零退出；修复后原测试与独立断言均通过，哈希未变。

同一目标原文：

> Fix add(a,b) in calc.py to return the sum described in README.md. Read the existing file before editing and verify by running the unchanged test_calc.py with the available Python interpreter. Modify only calc.py, no dependencies, added APIs or extra features. This workspace has no Git repository; use file tools for inspection and do not write outside the workspace. Keep implementation and verification in one coherent task, then finish after the required checks pass.

普通 `asteria goal` 参数一致：`--permission-level auto --model-strategy auto --no-research --max-iterations 3`。单次 goal 最长 240 秒，六次均未超时；没有更改审批或 provider 配额。独立检查包括四种 a × 四种 b 的 16 组求和与大整数 `10**30 + 1`。每次均 Review pass/1.00→Accept accepted，无重规划、无测试改写。

## 全部结果

goal 耗时不含 init、外部独立测试和显式 Review/Accept；goal 模型调用包含规划、执行与收尾。输入/输出 token 是 provider usage 的累计值，包含每轮重复上下文，不是唯一文本量；未区分缓存计费，不换算货币。

| 配对 / 顺序 | 代码 | goal 秒 | 模型调用 | 工具 / 失败 | 输入 token | 输出 token | 独立验收 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 / 1 | 48c08a4 | 48.59 | 9 | 13 / 0 | 121046 | 3524 | 通过并接受 |
| 1 / 2 | 37516da | 71.34 | 10 | 15 / 0 | 145239 | 5306 | 通过并接受 |
| 2 / 1 | 37516da | 43.98 | 8 | 12 / 0 | 101171 | 2717 | 通过并接受 |
| 2 / 2 | 48c08a4 | 71.04 | 11 | 19 / 1 | 164551 | 4626 | 通过并接受 |
| 3 / 1 | 48c08a4 | 53.11 | 8 | 12 / 0 | 100743 | 3277 | 通过并接受 |
| 3 / 2 | 37516da | 55.53 | 9 | 10 / 0 | 120260 | 3309 | 通过并接受 |

| 中位数 | 48c08a4 | 37516da |
| --- | ---: | ---: |
| goal 秒 | 53.11 | 55.53 |
| 模型调用 | 9 | 9 |
| 工具调用 | 13 | 12 |
| 输入 token | 121046 | 120260 |
| 输出 token | 3524 | 3309 |

三组耗时差（新版减旧版）分别 +22.75、-27.06、+2.42 秒。**本次数据不支持稳定降本结论**：新版两个配对更慢、一个更快，模型调用中位数不变，工具中位数少 1 次。三次每版的样本太少，且仅一个小型题目；全部成功也不能外推整体成功率。没有为得到更好数字追加样本、删失败或放宽验收。

唯一工具失败出现在第二组旧版：空参数调用 diff_workspace，实际返回缺 path/original 的错误。新版三次没有该错误，与 S102 补齐工具契约的修复方向一致，但单次差异不能单独解释全部耗时或证明因果。

## 可核实的新线索与研发决定

即使只修一个函数，两版首个执行请求的输入 usage 都约 1.83–1.91 万 token；执行模型分别跑了旧版 6/8/5 轮、新版 7/5/6 轮。累计输入的大头不能只用工具次数解释，下一步应分解固定上下文与工具反馈的构成，检查冗余，再决定是否修改提示装配。这里只记录 token 事实；尚未证明哪些字段可安全删除或能稳定降低货币成本。

本刀没有产品代码变更：没有证据支持继续加预算补丁或针对该题目写规则。S102 的评审正确性、权限事实等修复价值仍由原验收证据支撑，不能拿本次未降本否定其正确性收益，也不能把它们自动算成性能收益。

S103 旧样本失败原因已补正：原始 decision 显示模型尝试 Git 命令并重定向到工作区外 `/tmp`，权限门正确暂停。0 工具调用不意味着未选择工具或只叙述收尾。

## 证据与交接

本机 WSL `~/.cache/asteria-s104/` 保留 samples.json、sampling-driver.py 及六个 pair 工作区的 init/before/goal/独立测试/Review/Accept 日志和运行账本。驱动 SHA256：`49222bc65b9c9df91c8e870cf982daf6708995e4122fc9d60d0fbe4c00d66f8b`；代码快照仍在 `~/.cache/asteria-s103/code-{ref}`。每工作区 run id 都是独立的 `run-20261110-0001`，不可跨工作区混淆。

当前 ACTIVE_SLICE=S104，本刀六次预注册采样已完成。下一项为上下文构成的只读分解与通用去重评估，先确认安全字段边界再改代码。GLM 配额、独立 provider 及大型/数小时任务证据仍未关闭，既有未跟踪验证目录和本机凭据未入库。

文档契约测试 23/23 通过，差异空白检查通过。本刀提交只包含 ACTIVE 指针、brief、报告与计划文档；没有产品代码或额外维护命令。
