# S101：静态网页任务真跑与续作摩擦

日期：2026-10-15。任务来源：`benchmarks/beta_user_tasks.json#static_landing_page`。执行 brief：`benchmarks/reference_briefs/S101-static-page-dogfood.md`。

## 隔离工作区与真实路由

在系统临时目录 `asteria-s101-web-df0de542` 建空白工作区，加 `PRODUCT.md` 说明虚构产品 Daylight：每日聚焦三件事、本地优先、回顾。未读取或提交 provider key、路由文件与临时工作区。`model-check` 实际调用：medium MiniMax-M2.7 `call_ok=true/healthy`；strong 调用 `call_ok=true/degraded`，流式传输回退非流式。cheap 配置是 fake/offline，不能当真模型证据。本刀在 Windows 真跑；Linux 与跨 provider 的独立同题对照仍未做。

| 阶段 | 模型与工具账本 | 结果 |
| --- | --- | --- |
| 首次 Goal | 20:04:46–20:09:22，8 次模型调用（MiniMax 3、Zai 5），7 次工具调用（读 1、列 1、写 2、搜索 2、命令 1）。 | `index.html` 与 `styles.css` 已写，工作流自动接受。模型的 `run_command` 用 Python HTMLParser 解析文件并断言三个 ID 字符串存在，退出码 0；这**只证明静态结构检查通过**。 |
| 独立浏览器验收 | Chrome 直接打开 `file:///.../index.html`。桌面能渲染，CTA 点击后规划区出现、输入框获焦；390px 视口 `scrollWidth=390`，无横向溢出。 | 页面文案承诺“每天只选三件”，实际输入第 4 件后列表出现 4 项；该交互要求未通过。首次自动接受不能代表交互验收通过。 |
| 同 Session 续作反馈 | 明确告诉模型“最多三件、上限提示、删除后可再添加、验证真实交互”。20:13:02–20:22:44，7 次 Zai 模型调用、3 次工具调用（读 HTML/CSS、`node --version`），**0 次写入**；后续三轮均无工具动作，模型输出耗时累计约 562 秒。 | 为避免继续消耗而停止 worker，再用 `asteria cancel` 归档为 `cancelled`；文件仍允许第 4 件。未声称修复成功。 |
| 独立 medium 对照探针 | 第二个系统临时工作区 `asteria-s101-medium-a2393072` 复制相同页面，用 Plan 建任务，再通过内部 `ExecuteCommand(context_overrides={"execution_model_tier":"medium"})` 指定执行档；账本证实 5 次 `task_execution` 均为 MiniMax medium。模型写入 HTML/CSS；Chrome 实测第 4 件被拦、上限提示出现、删除后可再添加。 | **交互修复在对照产物中成立，运行任务仍 blocked**：多条模型选择的 `findstr` 命令真实返回 1；另两条 `run_command` 在 Windows 读 UTF-8 输出时由 GBK 解码抛异常，随后被报告为 `NoneType` 错误。此探针不算用户入口成功，也不能拿浏览器实测覆盖账本失败。 |
| 普通用户入口复跑 | 第三个隔离工作区复制首轮问题页，`asteria goal --permission-level auto --model-strategy auto --no-research --max-iterations 3`。账本共 21 次模型调用：GoalSpec/Plan 各 1 次 Zai strong，执行 19 次 MiniMax medium，证实已选档位从普通入口穿透；23 次工具调用。模型先生成环境探测任务并反复检查浏览器依赖，后在第二任务写入 `index.html`。 | 独立 Chrome 实测第 4 件被拒绝且提示可见；删除第一件后可补入，刷新后列表清空。模型的第三个验证任务未跑到；写页后多次模型调用无成功工具动作，曾试图写入第二任务 scope 外的测试脚本，被权限档拒绝。约 10 分钟后人工停止，`asteria cancel` 标为 `cancelled`。**页面交互通过，运行闭环未通过**。 |

首次 HTML 已在同目录可复查，浏览器截图仅保留本机临时文件 `screenshot-1792066239234.png` 和 `asteria-s101-mobile.png`。原始模型、工具、事件与进度账本位于该工作区 `.asteria/runs/run-20261015-0001/`。首轮 `run_command` 不是浏览器交互测试；没有独立 JavaScript 自动化测试通过的证据。

## 驾驭边界判断与后续

这轮没有证据支持针对 `glm-5.3-flash`、MiniMax 或 Daylight 写固定命令补丁。可核实的摩擦是：**强路由续作时工具停滞；medium 普通入口能写出交互修复，却因验证环境探测过长、跨任务写入被拒和后续无成功工具动作而未闭环。** 后几次调用没有可见的 `pre_final` 事件，可能涉及 JSON 回合格式修复；账本不存原始回复，不能断言每次均为格式错误。`max_iterations` 总保险丝仍在，新增连续 3 次无效 JSON 回合的早停保险丝，仅针对可由解析器确证的协议错误，返回 `budget_exhausted` 而不假报完成；不按 provider、命令文本或任务内容写分支。后续再取独立任务/OS 样本，判断通用耗时预算及交互验证入口。所有验证以真实工具观察为准。

## 本刀工程修复与验证

- `process_fence` 改为捕获原始字节，优先按 UTF-8、否则按主机编码解读；解码异常不再吞掉退出码。`RunCommandTool` 对缺失输出流返回空文本，避免二次 `NoneType` 崩溃。测试以真实 UTF-8 子进程输出复现并覆盖主机编码回退；命令网关与进程围栏 23/23 通过。原来导致 `NoneType` 的 `findstr /C:"MAX_TASKS = 3" ... index.html` 在修复后重放，返回码 0、stdout 340 字符且包含 `limit-alert`，未再崩溃。
- `RuntimeProfileBuilder` 现把已选择的模型档位写入执行上下文，避免 `ExecuteCommand` 因读不到 `execution_model_tier` 恒回退 strong。档位选择单测与真实执行请求的集成断言通过；相关 runtime profile / execute 测试 51/51 通过。
- 连续无效 JSON 回合现在最多调用 3 次模型；出现合法回合即重置计数。两条单测锁定早停与重置，`test_model_driven_turn.py` 22/22 通过。该边界未改变工具选择，也不能替代任务验证。
- `main@8236539` 的 [Verify run 38739392288](https://github.com/z243802480/mult_agent_code/actions/runs/38739392288) 三 job（Studio、Python 3.11、Python 3.13）均通过。
- 复查 `PlanAgent` 的通用任务分解提示：它已有少任务、工具可验及新测试文件需列入产物的原则，但没有约束“先建一个环境报告任务”，也没有明确新验证脚本必须落在**同一任务**写入范围。补两条规划约束：环境探测留在需要它的实施任务内；若任务可能新建验证脚本，将路径列入该任务的 `expected_changed_files`，并诚实说明交互检查不可用时的证据等级。PlanAgent/PlanCommand 14/14 测试通过。**效果尚未由真实模型复跑证明**，不能据此宣称 S101 闭环。
- 前两项通用修复的 `main@aae0484` [Verify run 38736896113](https://github.com/z243802480/mult_agent_code/actions/runs/38736896113) 三 job（Studio、Python 3.11、Python 3.13）均通过。**仍未证实**：原 Session 的三件事交互修复、普通入口完整 Review→Accept、Linux 真实模型路径。S101 保持活动，下一步先处理闭环耗时与验证策略，再决定是否换任务形状。

## 2026-11-06 追加：闭环验收真跑走通（run-20261106-0001）

前两刀的通用修复（输出解码、档位接线、JSON 早停）与规划约束（环境探测随实施任务走、验证脚本列入同一任务 scope）全部就位后，在全新隔离工作区 `asteria-s101-closure-a46bb32f` 做闭环验收。工作区重建缺陷页（文案承诺「每天只选三件」但可添加第 4 件、无上限提示、无删除）与 PRODUCT.md，走普通用户入口 `asteria goal --permission-level auto --model-strategy auto --no-research --max-iterations 3`。

结果：**首次完整走通 Goal→Plan→Execute→Verify→Review→Accept**。Plan 3 个任务，两条新约束兑现——task-0002 的写范围就是 `[verify_daylight.py, verify_daylight_result.txt]`（验证脚本规划期即在 scope 内，不再跨任务被拒），且没有独立的环境探测任务。task-0001 写入三项修复；task-0002 自建 headless 浏览器真交互验证（Playwright+chrome）三用例全过（第 4 件被拒且提示可见、删除释放名额、常规路径），期间 3 次被完成闸以「verification did not pass」正确挡下、软保险丝 3/6 自动续跑后转绿——这是闸在拒绝未验证的工作，不是缺验证死循环；task-0003 产出验证结论报告。`asteria review` pass/1.00 → `asteria accept` accepted。独立复测：preview 浏览器实操三项交互全过，375px 视口无横向溢出。

### 真跑暴露的新 friction：review 层 repair-loop 陷阱（已修）

首次 review 三次 partial/0.68 并路由 `verification_failed → resume`，但账本 append-only，历史分数结构性无法被 resume 修复——又一个修复循环陷阱，只是这次在 review 层。真因是三处与完成闸口径不一致：①`_deterministic_checks` 把全部历史尝试（含 17 条一次性废弃探针与环境探测）累计进验证通过率，而完成闸只判每任务**终轮**验证集；②review 证据窗口与观察行动计划没做「同命令取最新」去重（完成闸与 correctness-eval 早已这么做）；③失败分类存在 `"verification" in overall_reason` 子串误触发（通过率已 1.0 仍判失败）。修复把三处全部单一真源到完成闸的终轮证据（见 changelog 1.2.193），修复后同一 run 无需任何新模型执行即 pass/1.00。

### 诚实边界

- 最终交互验证 = 模型自建的 headless Playwright 脚本 + 我方 preview 浏览器独立复测；没有人类手点全流程。
- 本次仍是 Windows 单 OS 样本；Linux 与独立 provider 对照归 §16.2 第 14 行的后续采样。
- run 账本在 `asteria-s101-closure-a46bb32f/.asteria/runs/run-20261106-0001/`（本机临时目录），含 prompt/工具/验证全量证据。

## 2026-11-10 追加：Linux 采样环境探测

本机 WSL Ubuntu 可启动（Linux、Python 3.12.3），仓库经 `/mnt/f/mult_agent_code` 可读。以 Linux Python 从源码导入 `process_fence.run_fenced`，在独立临时目录执行 `printf linux_fence_ok`，退出码 0、stdout 与预期相同。这只证明 POSIX 命令围栏的最小真实进程路径。

首次探测时 Ubuntu 无 `pip`、`pytest`；普通 `python3 -m venv` 因缺 `ensurepip` 失败。该探测未形成 Linux 端 Asteria Goal→Accept 或独立 provider 样本。后续环境补齐与真跑结果见下一节；此环境缺口已解除。项目在 Linux 的必需依赖并不包含 pydantic/httpx，它们属于可选 future 依赖，缺少它们不能据此判定项目不可运行。

## 2026-11-10 追加：本机 WSL Linux 真模型验收通过

用户授权启动 WSL 并测试后，使用 Ubuntu/Python 3.12.3，在 Linux 用户缓存下建立隔离虚拟环境：`python3 -m venv --without-pip ~/.cache/asteria-s101/venv`，再由 PyPA 官方 `get-pip.py` 安装环境内 pip，并安装源码项目、pytest、pytest-asyncio。未安装系统或全局包。WSL 会话结束后 `/tmp` 的文件曾消失，故复用环境和工作区放在 Linux 用户缓存内。

- Linux 回归命令：`~/.cache/asteria-s101/venv/bin/python -m pytest tests/unit/test_process_fence.py tests/unit/test_model_driven_turn.py tests/integration/test_tool_registry.py tests/unit/test_runtime_profiles.py tests/integration/test_execute_command.py -q`，在 `/mnt/f/mult_agent_code` 执行。结果 **96 passed, 1 skipped，82.76 秒**；跳过的是 Windows Job Object 专属子进程清理测试。
- 路由：通过进程的 `ASTERIA_HOME` 使用本机既有路由配置，不复制配置或输出密钥。Linux `model-check --tier medium` 实际调用 MiniMax-M2.7 返回有效 JSON，`Call: ok / healthy`。cheap 配置虽仍为 fake，但该任务模型账本的 **12 次调用均为 minimax**，没有把占位调用计入真模型证据。
- 用户任务：隔离工作区 `~/.cache/asteria-s101/workspace`，普通 `asteria goal --permission-level auto --model-strategy auto --no-research --max-iterations 3`。要求生成 Daylight 本地静态 HTML/CSS 页面，含标题、三个益处、入门区与页内链接，无 JavaScript/远端资源/持久化；明确结构检查不能证明浏览器布局。此样本与 Windows 的交互修复任务不同，不能据此声称同题跨 OS 对照成功率。
- 运行 `run-20261110-0001`：规划 1 个任务，执行 1 completed/0 blocked，自动接受；12 次模型调用、12 次工具调用（todo_write 3、list_files 1、write_file 2、run_command 2、read_file 2、apply_patch 2）。期间一次 apply_patch 失败、后续成功修正，失败保留在账本。模型用真实 Python HTMLParser/文件断言检查内容、锚点、本地样式、响应式 CSS 与无脚本/外部资源，明确声明未证明浏览器布局。
- 显式 `asteria review --root ~/.cache/asteria-s101/workspace`：**pass/1.00**，0 follow-up、0 DecisionPoint；随后 `asteria accept`：**accepted / completed / review pass**。Linux 用户任务已完整验收。
- 独立检查：Windows Chrome 经 `file://wsl.localhost/Ubuntu/home/administrator/.cache/asteria-s101/workspace/index.html` 打开 Linux 产物；桌面渲染可读，所有页内链接目标存在；点击入门链接得到 `#getting-started`，375px 视口 `scrollWidth=360`，未横向溢出。浏览器在 Windows，不能记为 Linux 原生浏览器验证。截图仅在本机临时目录保留。

账本与最终报告在上述工作区 `.asteria/runs/run-20261110-0001/`；本轮未改产品代码，也未包含工作区已有的 smoke 未提交改动及未跟踪验证目录。**Linux 运行样本已取得，独立 provider 对照仍未取得**。
