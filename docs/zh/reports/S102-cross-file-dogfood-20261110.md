# S102：WSL 跨文件修复与重规划评审证据

日期：2026-11-10。brief：`benchmarks/reference_briefs/S102-cross-file-dogfood.md`。代码基线 `48c08a4`，工作区已有 smoke 改动保持原状；本刀不把那些改动算作新修复。

## 真实任务与独立验收

Ubuntu WSL/Python 3.12.3，复用 S101 的用户缓存 venv。隔离工作区 `~/.cache/asteria-s102/workspace`，run `run-20261110-0001`（与 S101 run 同名但工作区不同）。构造两文件缺陷：money.py 用 float 解析十进制金额，report.py 每轮覆盖 total 而非累加，空集合返回整数。README 规定精确 Decimal、空集合 Decimal 零、非法输入报错、不得修改原测试和添加依赖。

普通入口：`asteria goal ... --permission-level auto --model-strategy auto --no-research --max-iterations 3`，明确一次连贯修复与验证。初始 pytest **3 failed/1 passed**。模型修改 money.py 为直接 Decimal 解析，report.py 用 Decimal 零累加解析结果。既有测试独立重跑 **4/4 passed**；测试文件前后 SHA256 均为 `2633ec7e6ad445e3f699219a87ff1e4b91b24951a98e0a1f7be4073bd2963891`。独立额外断言：负数生成器合计 -10.00、空生成器 Decimal 零、10000 个 0.01 合计 100.00、空白包围金额解析，全部通过。

最初规划 1 task；两次自动重规划后前两 task discarded、第三 task done，最终完成契约 9/9 验证通过。累计 **61 次工具调用，5 次失败**：包括无 Git 工作区中尝试 git diff/status、生成器检查命令语法错误、缺参数 diff_workspace。失败未隐藏；最终产物可用，但小任务的重复验证/重规划成本仍高，不能从单样本外推成功率或效率。

## 独立 provider 边界

GLM strong 路由实际健康调用返回 HTTP 429（额度耗尽），未取得独立 provider 对照通过。最终 run 账本 **25 次模型调用：24 次 MiniMax 成功，1 次 Zai/GLM review 调用失败**；首次 review 在 GLM 429 后回退 MiniMax。cheap 虽配置为 fake，本次模型账本无 fake 调用。未复制、输出或提交 provider 凭据。

## 真跑发现并修复的产品缺陷

首次 Review 报 **partial/0.79、15/19 验证通过 → resume**，而活动任务已 done、终轮完成契约全绿。S101 1.2.193 只处理同一 task 的历史轮次；goal-level replan 新建 task id，旧 task 已 discarded，其终轮失败仍被 Review 与 CorrectnessEval 计分，造成 append-only 历史无法靠 resume 消除。

修复：两处评分排除计划中**明确 discarded 的 task id**；活动任务及未知归属的失败仍计入，原始账本完整保留。正确性旧账本回退路径同样排除明确 discarded 任务。`--rerun` 的独立重执行审计语义未改。无 provider、命令内容或题目特例。

回归先红：带 discarded 失败证据的现有集成场景在修复前得到 partial；修复后要求 Review pass，且实际 correctness signal 为 1.0。另加护栏验证 active/unknown 失败仍计入。真实 run 无需重做模型执行，修复后再审 **pass/1.00 → Accept accepted**。最初仅修 Review 判定时曾出现 pass/0.79，继续修正 CorrectnessEval 的同源口径后评分才一致，未把中间结果当完整修复。

## 交接

验证：Windows `test_review_command_latest_verification`、`test_review_command`、`test_correctness_eval_command` 与文档契约合计 **62/62 passed**；相同三组评审/正确性测试在 WSL **39/39 passed**。改动涉及的 Python 文件 Ruff 检查通过。代码与文档尚未提交，本轮未核对远端 CI。

运行账本、评审与最终报告在隔离工作区 `.asteria/runs/run-20261110-0001/`；独立验收未改账本。当前 ACTIVE_SLICE=S102。下一项先收敛无 Git 环境下的重复验证摩擦；独立 provider 对照须等实际可调用后再采样。S101 Windows/Linux 静态页验收保留为历史，不重复跑以填数字。

## 用户追加：代码质量改进

Review 与 CorrectnessEval 原先分别维护终轮选择、discarded 排除和命令/回查分类。本轮收敛到 `evaluation/verification_evidence.py`，让两处消费同一证据选择规则；正确性新旧账本路径的统计字段也改为统一构造，减少重复分支。移除原函数中大段历史叙事，决策来历留在报告。

同时补齐两条真实边界：①共享函数用 None 表示旧版未记录终轮列表、空列表表示明确的空终轮，CorrectnessEval 不再把空终轮/仅文件回查回退为历史命令成功；②缺失 task id 的证据不能互相覆盖，且无 id 的 discarded 任务不能据此排除所有无归属证据。非字典 data 的分类也安全降为非命令。

验证：Windows 与 WSL 的共享证据/评审/正确性相关测试均 **44/44 passed**，Ruff 检查通过，共享模块 mypy 定向检查通过。只读核对 S102 真账本的 correctness 与 Review 命令验证率仍为 **1.00**，没有新模型调用。新增行为回归覆盖空终轮、仅回查、非字典 data、无归属失败、终轮覆盖历史成功；旧版与独立 rerun 既有回归仍通过。改动尚未提交。

## 研发方向对账（用户询问·2026-11-10）

对照总计划 §1/§16.2、架构设计 §10 与本轮代码：近期工作仍服务于本地优先 harness、模型主导工具循环、真实证据和连续恢复。PlanCommand 已调用 PlanAgent；model_driven_turn 调用模型并在工具边界接 approval/pause，最近改动集中在环境事实、提示约束与证据选择，未新增题目/provider 特例。S101 Windows/Linux 与 S102 跨文件任务已有完整验收；这些小样本不能证明任意长期任务稳定性。

当前最直接的成熟度缺口是效率与恢复：S102 两文件修复累计 25 次模型、61 次工具、两次重规划，且真跑继续发现评审错误循环。共享证据逻辑已改善本次问题，但不能据此判定恢复重复责任已全系统消除。Studio 长时使用、较大代码库与独立 provider 的可重复表现仍缺足够本轮证据；GLM 429 是采样受阻，不是功能已实现或产品不支持该 provider 的证明。当前修改还在本地，未提交、未核对当前远端 CI。

原设计中的会话 fork、完整 cloud background，以及路线表 G12 定时触发/G13 best-of-N/G16 带鉴权 LAN 控制/G19 会话级隔离仍属待建设或需重新核实的范围，不以旧文档标记代替本轮全量代码审计。它们与已冻结的扩编排/强云隔离有独立决策边界，不能统称为遗漏。对本地单用户 Beta，优先收敛效率、恢复与 Studio 连续使用；对完整长期愿景，仍有整块能力缺口。

文档漂移实证：总计划 §2 仍写 promotion 必打断，§3.1 仍写新工作区默认关闭 parallel writes，而 §3.2/§3.3 与 AGENTS 已记录 auto-accept/并发专家默认开的后续授权；架构设计 §11 仍列 Typer/Pydantic，而当前 CLI/项目依赖并非该技术栈。本文仅标记漂移，不借此反向修改实现或恢复旧约束。7 月 ≈80% 是历史快照，本轮不是全系统逐项重审计，不给新的完成率。

建议顺序：先整理并提交已验的当前差异；再按 S102 真实摩擦降低重复验证/重规划成本，并做 Studio 同会话续作验收；随后补大一点的多文件任务和可用独立 provider 样本。证据稳定后再依据用户需求打开 P2 能力，不以增加功能数替代主路径质量。

## 诊断项收口（用户授权处理·2026-11-10）

### 实施

- 文档冲突：总计划 §2/§3.1/§3.2 改为后续已授权的权限档自主、auto-accept 与并发专家默认策略；架构技术基线纠正为当前 argparse/JSON Schema + SchemaValidator，Pydantic 为 optional future 依赖；前端路线 §6 的旧沙箱 P0 表述改为已降级。历史决策与有日期的旧审计快照保留，避免改写历史。
- 重复验证成本：执行提示提供真实 Git 元数据标记存在性（含父目录与 worktree .git 文件，不读取内容）、diff_workspace 参数契约，以及“检查通过后仅在相关变更/未解决疑问时重复”的通用指引。JSON 与原生工具协议复用同一 diff schema，工具仍返回真实失败，不把缺 Git 的命令错误改写为成功。
- 真跑搜索故障：目录搜索遇不可读文件原会中断；现在跳过该文件、保留其他匹配并在 warnings/unreadable_files 报告搜索不完整。可控 PermissionError 回归覆盖该边界，受保护路径规则保留。
- 本地测试入口：Studio smoke 与 Playwright 通过共享 test-runtime-env 从仓库相对位置注入源码路径，子进程不再依赖开发者碰巧给正确的 Python 做过 editable 安装。外部 PYTHONPATH 保留，路径分隔符随平台。初次未配置路径的 5 条 smoke 和 2 条 UI 失败记录为环境失败；修正后同组通过。
- 验收夹具：严格空终轮语义使一条声称已验证的 auto-finalize 旧夹具暴露缺失命令证据，夹具现写入完整 command/ok/returncode；生产代码不放宽空终轮。离线 gate 测试旧假设“strong 一定被执行”在正确档位接线后失效，改断言 smoke 成功但 gate 因缺 strong 使用证据失败，保留 gate 原有严格判定。

### Studio 真实多轮与更大任务样本

Windows 隔离工作区 `asteria-s102-studio-quality-mruhenm1`，Studio localhost 18872，session `session-1794295208717-76508e`。经普通 messages API 的 run/allow 入口执行，使用服务自身本机路由；没有模拟模型回复。浏览器实际打开该服务，主线程显示两个 conversationTurn、分别挂两个 run，均展示已验收。

第一轮五模块金额 CLI：初始原测试 5 failed/2 passed；执行后独立 pytest 7/7，测试哈希未变，负数生成器/空集合独立检查通过。run-20261110-0001 最终 10 次 MiniMax 模型、36 次工具、3 条失败（两条目录搜索权限错误和一次故意红测）；1 task done、0 重规划。显式 Review pass/1.00→Accept accepted。相比 S102 两文件样本次数减少，但题目、OS、测试条件不同，不据此宣称效率提高了某个百分比。第一轮模型还加了未要求的 --quantity/--json 选项，作为范围漂移保留记录，不把额外功能记为完成收益。

第二轮同 session 要求 --json 并补专门测试；该接口第一轮已被提前加入，因此本轮主要新增 test_cli_json.py。独立两组 pytest 8/8、真实 CLI JSON 返回 total 字符串 0.30、默认输出保留，原始测试哈希未变；run-20261110-0002 共 12 次 MiniMax 模型、15 次工具、0 工具失败，Review pass/1.00→Accept accepted。本轮证明同会话新目标的路由和新增测试，不能声称是首次实现该接口。

第三轮追加明确范围纠偏：仅允许 cli.py 与新 test_cli_discount.py，移除多余 --quantity，新增 --discount 并保留 JSON/普通模式。run-20261110-0003 共 17 次 MiniMax 调用、41 工具（8 失败），一次重规划后 done。独立 pytest 三组 13/13；范围外 Python 文件哈希全部未变；默认 0.30、10% 折扣 0.27、JSON total=0.27 和 --quantity 返回码 2 全部符合要求。Review pass/1.00→Accept accepted。故三轮真实续作和范围纠偏已有验收，效率还未达到稳定低成本，不能因加了提示就记为全面解决。

### 验证与未能关闭的边界

Studio 单测 269/269、完整 Playwright 13/13；不预设 PYTHONPATH 后 smoke 41/41、核心 UI 4/4 再次通过。WSL 相关 Python 67/67。全仓 Ruff 通过、mypy 棘轮无新增（60 条已追踪历史债），Studio ESLint 0 error/48 条现存 warning。初次全套 Python 1534 passed/3 skipped/39 deselected/1 failed（上文缺证据夹具），夹具和离线 gate 定向修复后 38/38，最终全套 Python 回归 **1536 passed、3 skipped、39 deselected（395.55 秒）**。含 real_provider 标记的脚本离线断言另行定向跑，夹具与 gate 相关组 38/38 通过。

独立 GLM provider 仍受额度限制，不通过读取/上传密钥或更改权限来绕过；独立 provider 对照仍未验收。五模块样本比两模块大，但仍非大型仓库/数小时任务实证，持续稳定性仍需后续采样。G12/G13/G16/G19、fork/cloud 属功能建设或冻结决策，不由本轮“问题修复”擅自开启。本轮不宣称已消除全项目历史类型债与 React 警告。

本轮诊断批次已完成本地验收并整理为独立本地提交；此前已有的 smoke 暂停重试实现及其对应新增测试留在工作区未提交，未纳入本次提交。既有未跟踪验证目录和 transcript 未入库。远端 CI 本轮未核对；独立 provider 限额及长期/大型仓库统计仍是明确未关闭项。浏览器最终确认真实会话显示 3 个 turn、3 条已验收结论。
