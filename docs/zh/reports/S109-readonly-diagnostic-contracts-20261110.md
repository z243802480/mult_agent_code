# S109 只读诊断证据契约与有界验证时限

状态：工程修复已通过本地回归和精确代码 CI；首轮失败留账。补齐规划指导后的重跑确有实现与测试进展，但自审越出工作区读取现行执行器源码，发生解答暴露，已正常暂停。最终独立检查 11/12，完整原测试加新增回归 1577 passed，范围干净，未 Review/Accept。自主目标与小时级可靠性未通过验收。

## 已复现与修复

基线新增回归 4 failed / 14 passed：只读任务无命令时无法明确选择文件证据；readonly diagnostic 的恢复被改为 implementation。复用现有任务 verification_policy，增加可选 readback_paths 与 timeout_seconds，schema 根目录/包内同步。

- 模型自己声明必需文件，只有 readonly diagnostic/verification 启用回读契约；每个路径要求最新真实 read_file 结果，缺失或可能写后过期则经原网关补读。路径不存在、保护/权限拒绝及最后一次同路径读失败都不能被旧成功或其他成功遮盖；预算硬闸后不补读，过期证据也不能算绿。
- 命令仍消费原实际结果。显式回读契约为空不能继承探索中的任意绿；旧任务未声明新契约时维持旧规则。探索错误继续回灌/落账，不按错误词或题目筛掉；本刀没有扩大原有 diagnostic expected-failure 语义。回读证明 inspection，不证明诊断语义或软件修复正确；回读独立测试确认 CorrectnessEval 不把它算可执行代码验证。
- readonly diagnostic 重规划保留原 kind、completion_contract、空写范围、读范围、文件/命令证据和时限，不再为了 brief allowed_writes 变写任务。验证种类仍保持原 S107 行为；真实实现缺陷不自动授写权。
- 暴露既有工具 timeout_seconds，默认 command=60 秒、tests=120 秒不变；声明的验证时限经实际 RunTestsTool 透传，不改命令。任务/native schema 要求正整数，Python 工具继续接受正有限数；零、负数、布尔和无效值不能执行。真实超时仍失败。

相关端到端测试覆盖探索超时/读拒绝后必需回读完成、缺失、受保护路径、无 read 权、显式空证据、必需命令红和 legacy 判据；Execute→Replan→Execute 正反例同时覆盖 diagnostic/verification，未改源码或写权。

## 真实样本与追加上下文修复

目标使用历史真实 Asteria main@57f6274 的完整跟踪源码，修工具批次前缀/异常归属、canonical/别名来源、实际运行包装器与 MCP/skill 意外异常证据。执行器以 6a0824e（生产代码同 9982169）加本刀冻结改动运行，目标源码与执行器分离，不随仓库后续编辑热改。

独立原 S108 oracle 9 项保持原字节，SHA256=2b62de7261d06446cc106cb38e3507ad64fdb36f9f10116cfef18b78206be268。追加的 runtime oracle 原样继承九项并补实际包装器/别名持久化/MCP 失败持久化，共 12 项，SHA256=9b34ddd3dd1f81830805731b0494327261f994146618fc949c35101877ab45fc。两个脚本位于 benchmarks/dogfood/，均不提供给模型；旧版本基线 10 failed / 2 passed，原相关回归 46/46。

首轮 WSL ~/.cache/asteria-s109，229.22 秒、22 次 MiniMax-M2.7、69 工具/5 失败、0 协议纠正、1 重规划、1 compact，输入 787171 / 输出 17969 token。模型自拆出诊断任务，但虚构 docs/master-plan.md、docs/briefs/S109.md 并列为必需回读，验收按真实缺失阻断；恢复仍保持 diagnostic，证明性质保留接线可达。未修改源码/原测试、无越界；oracle 仍失败，原全套通过；本方正常 pause 一次，未 Review/Accept，解答修改/额外提示 0。不计自主完成。

继续回代码核实发现：ContextLoader 已有 root_guidance，但 PlanAgent._user_prompt 仅给 GoalSpec 和截断路径清单，规划阶段根本没看到 AGENTS.md 的真实文档路径。总计划 §16 顶部 brief 索引还停在 S107，亦已纠正。补丁只把现成 root_guidance 的路径/限长文本/截断标记放入规划输入；不扫更多目录，不硬编码 Asteria 路径，不把假路径自动映射为真路径。提示只以已知真实路径声明必需证据。

同时实证：本仓库总计划 >500 KB，ReadFileTool 的总文件 200 KB 拒绝发生在 offset/limit 窗口逻辑前，连所建议的窗口也无法读取。现对大文件流式分页并限制每次输出字节/行数，巨型单行也分块跳过；未知总行数标 None，小文件旧行为保持、PathGuard 不改。通用多字节/长行/分页/保护路径回归通过，实际总计划窗口 690–701 行成功读取 1988 字节。原生 schema 也暴露原有 offset/limit。

重新冻结的独立重跑在 ~/.cache/asteria-s109-grounded，目标文本与固定独立 oracle 不变，仍从相同历史源码开始，仅更新工程指导与执行器；不是续写首轮解答。运行内不手改解答/追加提示。若模型未拆出诊断任务，不能把样本称为真实独立诊断流程证明；若完成也只是已知历史回归目标及当前工程指导下的一次成功，不外推陌生问题或一到三小时稳定性。

重跑的规划 JSON 不可用（`invalid syntax (<unknown>, line 98)`），`task_plan_model_fallback` 如实记录后使用模板的一个 implementation 任务；不能把此轮算模型自主分阶段规划证明。模型自行修复 frozen MCP result 的 `setattr`、旧进度事件顺序和自建夹具错误，新增 6 项回归及源码导入检查；原集成测试两次各 310 passed / 1 skipped / 42 deselected（241.49 / 238.50 秒），完整原测试加新增回归 1577 passed / 4 skipped / 42 deselected（265.77 秒）。重复集成运行有真实成本，不能只记最后的绿灯。

重跑最终执行 2077.87 秒（约 34.6 分钟），63 次 MiniMax-M2.7、207 工具/25 失败、执行协议纠正 0（规划 JSON 失败另计）、重规划 0、compact 1；输入 4547025 / 输出 57424 token。修改三个允许的原生产文件，新增 narrow helper 与一份 6 用例回归，原测试/指导/schema/配置哈希不变，execute 包装器/imports 外的 AST 不变。控制方人工解答修改/提示 0、正常暂停 1；解答暴露另记，不能据前两项声称无介入成功。

暂停后固定独立检查 **11 passed / 1 failed**：`test_alias_provenance_is_preserved_in_model_and_disk_evidence` 要求模型观察及 raw observation 的 `data.model_tool_name`，实际为 None；独立附加检查核实反馈 summary 仍含 `[grep -> search_text]`，progress 的结构化 `model_tool_name` 仍为 grep。因此不能写成“全部别名来源丢失”。题目要求保留来源，但没有指定该字段；此 oracle 对字段表示比文字需求更具体，后续须预先明确字段契约/等价表示，不能在运行后换规则把这轮改绿。原 9 项 oracle 全过，本轮新增 3 项中 2 过；保留原字节与原失败结论。

暴露后模型又跑原全套 1577 passed（266.37 秒）；控制方独立重跑全套为 **1577 passed / 4 skipped / 42 deselected**（pytest 267.63 秒，外部总耗时 267.86 秒），无超时。两个 model-routing 警告来自确定性路由单测，真实调用账本 63 次均为 MiniMax；开头 cheap=fake 警告不等于实际用了 fake。最终 state=paused、task=ready、workflow=needs_action，`accepted=false`，Review/Accept 均未执行。历史目标的解答未复制回主仓库。

**解答暴露否决**：2026-11-10 22:45:05–07 +08:00，`toolcall-0198` 对比目标与相邻 `runtime-frozen` 的哈希，`0199/0200` 直接 diff 现行执行器的 model_driven_turn、gateway、execute 和批次 helper；该执行器含 S108 已修复实现。`0202` 随后于 22:45:49 修改目标投影和回归。此前完整测试绿不能证明所有独立反例已修，也不能证明后续修改未受现行解答影响。控制方未人工改解答/给解题提示，但实验把已修复源码放在相邻可读目录，隔离设计不足；已正常 pause 一次留账，不把“控制方未改代码”等同“没有解答暴露”。暂停只在下一 turn 边界生效，已开始的测试仍允许结束；随后独立检查仅评价最终产物，不恢复此样本的独立自主证明资格。不用此事扩展本地 OS 沙箱路线，也不按路径名给生产模型打补丁。

## 边界、验收与交接

普通 goal / auto / no-research / max-iterations=32，单次最多 3600 秒，默认全局预算不变。正常本机 medium 路由加载，进程临时禁用未配置的 strong/cheap，实际 provider 以 model_calls.jsonl 核对；密钥未输出/迁移/入库。模型不得改原测试、依赖/schema/指导及无关生产文件；execute_command.py 仅 wrapper/imports 可变，外部 AST 检查其余节点不变。全部原始输入哈希及新文件范围独立审计，完整原测试和 12 项 oracle 通过才 Review→Accept；不会把读取文件或 CI 绿冒充修复了目标代码。

本地首批完整 Python 1615 passed / 3 skipped / 42 deselected（431.31 秒）；追加规划指导/大文件分页后最终相关 101 passed（44.21 秒），Ruff src/tests/benchmarks 与 mypy 棘轮无新增（60 项既有债）。最终生产提交 `c3d91922a939c2906e17d5f6f9459edf94a8acc2` 的 [Verify 42832748680](https://github.com/z243802480/mult_agent_code/actions/runs/42832748680) 已完成，Python 3.11/3.13 与 Studio 三 job 全绿。冻结执行器全部 Python 生产文件与该提交规范化换行后逐文件一致；真实重跑的独立检查结果如上。远端缺 key 的 keyed proof 仍 NOT RUN。

两个缓存根目录各有 runtime-frozen、repo-workspace、before-hashes.json、production-hashes.json、goal.txt、进程起点、result.json、目标及独立验收日志；run_id 均 run-20261110-0001，必须带目录区分。Windows 临时目录有 asteria-s109*-driver.py 与 asteria-s109-eval/ 两个预先固定脚本。未跟踪验证目录、本地密钥/路由不入库。

ACTIVE_SLICE=S109，工程收口，完整独立自主验收未过；本轮已停，不因部分全绿改判无暴露自主完成。下一步按顺序：①先把实验的参考源码/隐藏验收与目标布置分开，明确禁止读取执行器作基线/解答，不依赖本地 OS 强沙箱；选择不含已修复参考实现的目标，预先定义可观察验收及等价表示。②参考现有执行协议的有界错误反馈，评估规划 JSON 一次失败立即回模板的最小恢复；保持 schema/权限/预算和 offline fallback，不猜改模型含义。③再做一轮预注册真实目标，记录重复验证/成本与独立结果，不按时长凑数。本轮不再追加模型样本，下一刀编码前需新 brief。
