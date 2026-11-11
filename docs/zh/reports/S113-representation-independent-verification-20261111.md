# S113 — 检查器正确性与真实多文件续作闭环

2026-11-11，用户授权两个迭代中的第二轮。**本刀已验收**：修复验收器对内部表示的误约束；新版检查器在新登记的干净目标上通过独立行为、范围和连续性检查，并正式 Review pass/1.00→Accept accepted。没有修改产品运行时来迎合题目或模型。

brief：`benchmarks/reference_briefs/S113-representation-independent-verification.md`；预注册与检查器提交 `9c7f014`。该提交的 [Verify 42946426133](https://github.com/z243802480/mult_agent_code/actions/runs/42946426133) 中 Studio、Python 3.11、Python 3.13 三个 job 全绿。生产执行器仍为 `1891f8e`（与当前 src/schemas 无差异）。

## 修复及检查器自验

S112 冻结 oracle 曾从 `db.storage.writes` 读取测试自定义计数器，错误要求合法存储包装器透传这个字段。S113 新增版本化 oracle `benchmarks/dogfood/tinydb_readonly_oracle_s113.py.txt`：保有测试创建的底层 Memory/JSON 存储引用，直接观察计数和数据，不探测产品包装器的私有字段。公开 API、拒写时序、字节不变、嵌套读取隔离、允许文件及其他判据不变。

新 oracle SHA256 `9e282df69c7994c821a0786a69be476f373d13e1eb0dd521b0859af620395788`；公约仍为 `31f05d93faf2a100d8d8054c487cc343ea83922505075963b38e58d7f22c6c18`。原 S111/S112 oracle 的 `cebe977e…` 哈希及失败日志原样保留。对 S112 工件使用新版 oracle 的事后诊断为 20/20，但**不替换其原冻结红记录，不追认它已独立接受**。

新增 8 个检查器回归：内存/JSON 的合法不透传计数器包装；写后抛错、回调后抛错、原地嵌套修改、未抛错、返回文档别名及磁盘字节修改六类反例。合法包装通过，坏副作用仍被拒收。测试只有最小观测/播种 doubles，不依赖 TinyDB 安装，不提交真实实验解答。隔离实验协议同步加入“先验证 grader、版本化修正、事后诊断不覆盖冻结结果”的规则。

## 新登记真实样本

- 全新上游 TinyDB `edff96aeb2616402e9489d46e90a592c05565621`，保留 MIT 许可证与原测试；归档哈希与 S111/S112 相同。原测试基线 227 passed / 1 skipped，缺 API 的独立 oracle 基线为红。
- 三处隔离：执行器 `~/.cache/asteria-runtimes/s113-1891f8e`（仅 src/schemas）；目标 `~/.cache/asteria-workspaces/s113-tinydb`；外部证据 `~/.cache/asteria-evaluations/s113-tinydb-20261111`。原始 registration/result、输入/执行器哈希、checkpoint、五份账本前缀、独立验证及 Review/Accept 日志均在那里。没有把隐藏检查、旧解答或控制器放入目标。
- 同原公开 goal（SHA256 `9f75426e2b2824f2329625a79d40ac9f6a45460685915baf0ecb494632d73f7b`），普通 goal / auto 权限、现有 MiniMax-M2.7 路由；原 3600 秒共享时限与原预算，没有调高计数或放松门槛。
- `run-20261111-0001`：初轮 PID 387、474.51 秒，首次非空源码改动后正常 pause；暂停时 41 模型/149 工具，已有 errors.py 与 __init__.py。新 PID 835 正常 resume 同一 run，574.76 秒。**执行总计 1049.27 秒（17 分 29.27 秒）**；另正式 Review 57.40 秒，Accept 0.47 秒。不把暂停控制动作当解题提示，不凑时长。

## 独立验收结果

| 检查 | 结果 |
| --- | --- |
| 固定公开行为 oracle | 20/20，通过，0 错误 |
| 原全套 + 模型新增回归 | 236 passed / 1 skipped（新增 9 项，含有效行为断言与异常断言） |
| 多文件与允许范围 | 原四处生产文件修改，新增 errors.py 和 tests/test_readonly_s111.py；无越界原文件/新文件，原测试/配置/许可证哈希保持 |
| 来源与执行器 | imports 绑定当前目标；冻结执行器所有源文件哈希不变；全部模型调用真实路由 |
| 跨进程连续性 | 唯一 run、goal_spec 字节不变、暂停前五份账本前缀保留；控制方代码编辑/解题提示均 0 |
| 累计计量 | 暂停 41→最终 91 模型，149→315 工具；输入 1,716,471→4,370,383 / 输出 33,641→66,751 token，最终 cost 与原账本逐项相等 |
| 独立检查后正式评审 | Review pass / 1.00（3 条声明验证命令通过），随后显式 Accept accepted |

暂停时本轮尚无 done 任务，结果里的 completed_tasks_preserved 是空集合判定，不能额外当成已完成任务保留的证据；该性质的真实非空证据来自 S112 的研究任务。运行时先前已有 auto-accept，但独立接受只在外部检查与显式 Review/Accept 以后成立。

已审计全部 315 条完整、可解析 input_summary：179 read_file、21 search_text、91 run_command、6 apply_patch、1 write_file、7 run_tests、3 list_files、6 todo_write、1 remember。文件参数均为本目标公约/原源码/原测试/生成文件；92 种去重命令均为本目标读取/修改/测试或来源绑定，Python here-doc 也已检查，无运行时/安装包源码、相邻解答、父目录或网络访问记录。记忆工具写入的是目标工作区的架构笔记，不是控制方注入提示。不将这种行为审计冒称 OS 强隔离。

工具失败 11 次（5 次 patch 格式/上下文、一次读不存在文件、一次缺命令参数、两次 shell 非零、一次新增测试非零、一次把文件当目录）。模型自行换工具、修代码/测试并继续，未人工介入。没有规划 fallback/replan；2 次 context_compacted。记录字段 protocol_errors=2 不据此扩大成纯 JSON 错误数量。

## 工程验证、记忆与下一步

本轮 Windows 检查器 + 文档契约 **31 passed**；WSL 检查器 + 跨进程暂停/恢复 + checkpoint **17 passed**；`ruff check src tests benchmarks` 通过；mypy ratchet 无新错误（60 条既有 baseline，未改 baseline）；精确提交 CI 三 job 全绿。

更新本机 `.asteria/memory/README.md` / `local_agent_operating_memory.md`：撤销 10 月重审计队列仍待做的过时说法，写入两轮真实证据、当前指针与下一步；旧 `route_alignment_20261014.md` 标为历史快照，archive 原始证据保留且不重新挂入活跃 JSONL。源码目录、原有六批未跟踪验证输入及本地 routes/keys 没有进入提交。总计划 §6 同步消除“已默认启用的专家并发写仍待放量”的歧义；OS 沙箱收口结论沿用现行 ADR-0030。

**边界与下一刀**：这证明一个真实多文件目标可在约十七分钟内自主实现、修错、跨进程续作并通过独立验收，不证明一到三小时可靠性或独立 provider。重复源码读取很多；正式 Review 实际输入 165,253 token，结束时 context ratio 0.826 / near_limit（此前有 180,091/200,000 的压力记录）。S112 与 S113 使用相同执行器/公开目标却轨迹和成本不同，不能归因于不可见的 grader 修正，更不能宣称稳定降本。下一优先是**执行/恢复中的重复读取及 Review 上下文构成诊断**：先记录与归因，再选择提示引导/已有上下文管理的通用修复；不直接限读、加预算或按模型/题目写特判。GitHub 双 key proof 继续 NOT RUN，不作为研发前置条件。
