# S115 — 文件读取可见范围与续读提示

2026-11-11，用户「继续修正吧」，承接 S114 的已核实问题及总计划 §16.2 第 27 项。brief：`benchmarks/reference_briefs/S115-file-read-visible-range.md`；代码提交 `f431153`。

**本刀已验收：Windows 完整 1669、相关 Windows / WSL 各 95 项通过，精确代码 CI 三 job 全绿。** 文件反馈标题只声明模型实际可见的行，完整行优先，有后续行则给准确 next_offset；部分长行不会被当成完整读取。维持 6,000 字符输出上限，没有改变文件原始 content、分页、路径保护、权限、预算或完成验证。

## 旧问题与复现

真实 S113 的 179 次读取里有 40 次渲染字符截断，offset 实际生效，不能诊断成分页未接线。原 `_model_facing_payload` 先按后端选中窗口构造标题，再用字符截断整个字符串：小文件没有 line_end 时标题出现 None；大窗口显示的结束行超过实际输出，还可能在行中途截断。旧 `_clip` 的截断提示附加在 6,000 字符之后，实际文件 payload 可超过该值。

先写 12 个回归实例，旧版 **10 failed / 2 passed**，直接复现范围/续读/长行/空文件的问题；修复后全部通过，另补两个 UTF-8 字节边界实例，共 14 个新实例。

## 改动

- 新增纯渲染模块 `core/file_read_payload.py`，由原 `agent_harness._model_facing_payload` 的 read_file 分支调用；不访问文件、不另建状态、不改变原 ToolResult 或持久化 schema。
- 标题使用 `(visible lines X-Y of T)`，X/Y 由实际展示内容计算，T 未知时明说 unknown。去掉 None/虚构空区间；空文件与越过末尾明确说明，缺失 content 不被制造成“空文件”。
- 在现有 6,000 字符内同时容纳标题、完整行和续读说明。第一条未展示的完整行通过 `next_offset=N` 返回，提示用同一 read_file 的 offset=N 继续；不增加工具参数或维护命令。
- 一行本身过长、或后端字节窗口已截断尾行时，标为 `partial_line=N; not fully read`。不发出越过该行剩余内容的 next_offset，也不错误声称缩小行数 limit 能恢复该长行剩余部分；提示用适当可用工具定点查看。
- 剩余字节装不下一整个 UTF-8 字符时，区分“上一行完整、下一行未展示”与“连一个字符都未展示”：前者从下一行继续，后者明确部分可见，不误报空文件。
- 现有模型工具说明补充 next_offset/partial_line 的语义。S114 Review 去重保留不能从 data 重建的唯一/旧文件 payload，renderer 升级不会把旧文件证据洗掉。

工具原 summary / data 的 line_start/line_end 仍描述**后端实际选中的读取窗口**；新 payload 的 visible 标题描述**模型实际看到的窗口**，两者不混为一谈。execute/run、自主环、风险路由和 provider 均未改动，无按模型或题目特判。

## 纯工具实证

固定旧渲染函数来自 `aa3e4f0`，新版为 `f431153`；同一真实 ReadFileTool 结果上对比。没有调用模型，也没有改写旧 S113 实验。临时输入及 result 在本机 Temp `asteria-s115-render-probe-20261111/`，不提交原始探针数据。

| 场景 | 旧版 | 新版 |
| --- | --- | --- |
| 700 行 UTF-8 文件的首屏标题 | `(lines 1-None of 700)` | `(visible lines 1-83 of 700)` |
| 首屏实际输出 | 第 85 行中途结束，6,056 字符 | 83 个完整行，5,999 字符，next_offset=84 |
| 按新版提示继续 | 旧版没有明确起点 | 9 页按原顺序覆盖全部 700 行，无漏行/重复，源文件 hash 不变 |
| 新版每页字符数 | — | 5999 / 5935 / 5952 / 5952 / 5952 / 5952 / 5952 / 5952 / 3630 |
| 单行一万多字节文本 | 只给泛化截断提示 | 6,000 字符，partial_line=1，不给跳过剩余内容的 next_offset |
| 空文件 | 无 payload | `(empty file; total_lines=0)`，不假造行范围 |

逐页测试也走完整的 ReadFileTool→ToolObservation→`_observation_feedback` 通道，并对最终行号和内容逐项与原 700 行比较；不是只测试字符串标题。

## 验证与边界

- Windows 相关 95 passed；WSL 同组 95 passed，包含模型工具表面、执行循环、gateway、既有文件窗口及 Review 投影回归。
- 文档契约 23 passed，Ruff 通过，mypy ratchet 无新错误（60 条既有 baseline，未修改 baseline）。
- Windows 完整 pytest：**1669 passed / 3 skipped / 42 deselected**，453.43 秒；两条既有混配路由 fixture 告警，无新失败。
- 精确代码 CI：[Verify 42953846909](https://github.com/z243802480/mult_agent_code/actions/runs/42953846909)，在精确代码 `f4311536b3f30026964a676475de338e2807a39b` 上 Studio / Python 3.11 / Python 3.13 全绿。

本刀只证明工具反馈与续读边界正确，没有新真模型自主目标样本，不能外推“模型一定不再重复读”或总调用成本下降。下一优先是在独立真实任务中观察模型是否触发并采用新版提示；先固定公约/原测试/oracle/预算与读取审计，不凑时长、不对同一失败题刷绿。小时级/独立 provider 的可靠性仍未证明，GitHub keyed proof 仍 NOT RUN。

计划与本机记忆已按最终回执同步；原六批未跟踪验证输入、原实验账本、私有 routes/keys 均不纳入提交。
