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

首次 HTML 已在同目录可复查，浏览器截图仅保留本机临时文件 `screenshot-1792066239234.png` 和 `asteria-s101-mobile.png`。原始模型、工具、事件与进度账本位于该工作区 `.asteria/runs/run-20261015-0001/`。首轮 `run_command` 不是浏览器交互测试；没有独立 JavaScript 自动化测试通过的证据。

## 驾驭边界判断与后续

这轮没有证据支持针对 `glm-5.3-flash`、MiniMax 或 Daylight 写固定命令补丁。可核实的摩擦是：**强路由续作时反复叙述下一步且工具停滞；同一交互修复在 medium 对照中写出，但验证被真实命令失败及命令输出解码 bug 阻断。** 当前 JSON 协议修正与 `max_iterations` 保险丝防假完成，却没有及时制止长时间无工具进展。后续再取一个独立任务/OS 样本，决定是否引入通用的无进展/耗时预算；评估更适合交互产物的浏览器验证工具或按任务加载技能。所有补充验证须以真实工具观察为准，不能把字符串检查包装成“交互已测”。

## 本刀工程修复与验证

- `process_fence` 改为捕获原始字节，优先按 UTF-8、否则按主机编码解读；解码异常不再吞掉退出码。`RunCommandTool` 对缺失输出流返回空文本，避免二次 `NoneType` 崩溃。测试以真实 UTF-8 子进程输出复现并覆盖主机编码回退；命令网关与进程围栏 23/23 通过。原来导致 `NoneType` 的 `findstr /C:"MAX_TASKS = 3" ... index.html` 在修复后重放，返回码 0、stdout 340 字符且包含 `limit-alert`，未再崩溃。
- `RuntimeProfileBuilder` 现把已选择的模型档位写入执行上下文，避免 `ExecuteCommand` 因读不到 `execution_model_tier` 恒回退 strong。档位选择单测与真实执行请求的集成断言通过；相关 runtime profile / execute 测试 51/51 通过。
- 这两项是通用执行边界和路由接线，未按模型名或 `findstr` 文本写例外。**仍未证实**：原 Session 的三件事交互修复、对照任务的 runtime 验证通过、Linux 真实模型路径。S101 保持活动，待本次改动远端 Verify 和一次用户主路径复跑后再收口。
