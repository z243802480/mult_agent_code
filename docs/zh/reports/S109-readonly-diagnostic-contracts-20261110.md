# S109 只读诊断证据契约与有界验证时限

状态：工程修复已通过本地回归；真实历史仓库任务首轮失败留账，补齐规划指导后独立重跑 RUNNING。未宣称自主目标或小时级可靠性已过。

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

## 边界、验收与交接

普通 goal / auto / no-research / max-iterations=32，单次最多 3600 秒，默认全局预算不变。正常本机 medium 路由加载，进程临时禁用未配置的 strong/cheap，实际 provider 以 model_calls.jsonl 核对；密钥未输出/迁移/入库。模型不得改原测试、依赖/schema/指导及无关生产文件；execute_command.py 仅 wrapper/imports 可变，外部 AST 检查其余节点不变。全部原始输入哈希及新文件范围独立审计，完整原测试和 12 项 oracle 通过才 Review→Accept；不会把读取文件或 CI 绿冒充修复了目标代码。

本地首批完整 Python 1615 passed / 3 skipped / 42 deselected（431.31 秒）；追加规划指导/大文件分页后最终相关 101 passed（44.21 秒），Ruff src/tests/benchmarks 与 mypy 棘轮无新增（60 项既有债）。精确提交 CI 与真实重跑待回执。

两个缓存根目录各有 runtime-frozen、repo-workspace、before-hashes.json、production-hashes.json、goal.txt、进程起点、result.json、目标及独立验收日志；run_id 均 run-20261110-0001，必须带目录区分。Windows 临时目录有 asteria-s109*-driver.py 与 asteria-s109-eval/ 两个预先固定脚本。未跟踪验证目录、本地密钥/路由不入库。

ACTIVE_SLICE=S109。当前 DoD：相关工程验证、精确 CI、核对一次完整真实任务的独立 oracle/全原测试/范围/Review→Accept；未达则写清失败，不重试刷绿。当前重跑 RUNNING，尚不计成功。
