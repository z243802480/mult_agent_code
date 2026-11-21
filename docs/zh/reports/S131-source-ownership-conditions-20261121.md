# S131 证据来源唯一性与原始适用条件

日期2026-11-21。基线a34a250；生产修复冻结7b33b18a839151f50bbdea8e15d171448c80b0d6。来源关联工程与正向后续正式Review/Accept已验；旧坏件Review仍漏检，S131保持开放。

## 原始要求与派生判据的实际边界

只读复核上一坏件快照和41条旧执行前缀：原请求1167字符、指导完整；独立重建的Review输入子集首屏criteria只有user_request/current_project_guidance，31项原判据中的派生项已按需。当前两方法的最近returncode为0，但coverage仍unassessed。此重建不是原完整模型请求的hash等价，不能从摘要推断模型内部理解。

“派生判据直接在首屏覆盖原要求”的假设不成立。过去实际局部方法仍绑定28字符实现锚点，真实退出0不能认证原始样式条件；没有证据支持加提示、强制工具数或改语义门禁。该旧前缀无外来run、无重复call/observation身份；下述来源修复未在旧误判中触发，不签因果。

## 确认并修复的通用来源问题

原review_focus.task_evidence仅按task_id关联，可借用其他run同名任务的观察；重复call_id/observation_id、无run绑定或重复任务身份也可能获精确关联。ReviewEvidence只检查call_id唯一，会为重复observation_id生成两个来源引用。反例确认后采用共同的当前run+双身份唯一资格，不猜选正确行、不修改原始账本或覆盖判断。

最早匹配写入的身份有歧义时，diff基线保持未知，不能丢掉它再退到较晚备份假称原始基线。未触及该文件的其他备份仍可继续查找，路径/链接/manifest/容量守卫原样。任务来源、按需观察/方法快照使用同一资格和有界窗口；重复任务不选owner，omitted_tasks按实际缺项记。权限/原始请求/提示/模型JSON/schema和shell均未改。

参考[Codex独立Review](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/src/tasks/review.rs)不继承initial_history且限制评审能力的机制，只参考来源与上下文隔离，不引入agent/新编排或复制实现。

## 工程验证

首9个实例原版8失败/1通过，修复7b33b18的相关Windows61通过1跳过/WSL62、完整2288通过。收尾另补1个active/discarded同ID反例，旧版红→最终b1926fb绿；最终Windows相关62通过1跳过21.17秒、WSL63通过38.20秒。含跨run/重复身份/缺少绑定/重复任务/最早歧义不回退及真实Review→Accept等原回归。Ruff和类型棘轮无新增（60 known/18不再出现），五离线基准通过，3.11语法检查通过；最终b1926fb完整Windows2289通过/8跳过/42排除/2警告，644.56秒；Ruff/类型/五基准再次通过，最终文档契约23通过。

## 新真实验证

五场初始真模型冻结7b33b18；最终b1926fb只补任务身份计数需包括discarded的一行守卫和对应测试。五场任务ID均唯一（含discarded），两版focus纯函数结果逐字等价；此0模型重放只证明focus投影，不冒充整个原模型请求hash相同。后续正式Review/Accept直接使用最终b1926fb冻结运行时，版本分开记录。

### 原始适用条件控制

同一原请求规定整数非负时保持数值，负数时同时保留符号和幅度；登记方法只检查正数5，三个实现均真实退出0。controller准备工件与2条种子，不运行Goal/Execute，不向Review透露外部负数/零/正数判据。

| 场景 | 独立判据 | 标准Review | 新模型/自主工具 |
| --- | --- | --- | --- |
| abs(value)，负数符号丢失 | 拒收 | 8.21秒fail/0.3，明确指出正向检查不覆盖负数 | 1 / 0 |
| return value | 合格 | 9.01秒pass/1，执行原方法及0/-7检查 | 2 / 3 |
| 有效替代value + 0 | 合格 | 7.21秒pass/1，接受不同实现 | 2 / 2 |

0工具的坏件判断有当前源代码和明确反例支持，不以工具数单独判错。三场5模型59901入/1539出，5自主工具+6controller种子，原件保持，所有Accept NOT RUN。它证明定向条件辨识与接受有效替代的能力，不能外推文档坏件或稳定可靠性。

首bad准备fixture使用不完整手写policy，在实际工件写前预算KeyError，0模型；原stub和1条孤立失败观察、0调用记录原样保留，单列而不混正常账本对账。只修临时诊断接线为原生policy loader+run_config，再新建condition-b三场各一次。生产源码没有为该fixture改预算、守卫或日志。

### 原真实坏件与自然正向

同原自然目标/指导/基线/v1/v2/13控、32轮900秒，旧坏件标准Review与自然正向各一次，无oracle/在途解答或清理批准，不续旧场或无改复采。

坏件37.21秒/3新模型/3真检查：自拟doctest包装先报参数错误再自行修正，项目271过1跳过、局部exit0后仍pass1，明确声称样式满足却漏标题29/线28。独立拒收，不Accept；覆盖仍null/unassessed。原始条件/当前差异均在快照，无截断，也没有触发本刀来源资格守卫，不为旧误判编造因果。

正向771.04秒原生completed/ACCEPTED（既有auto-finalize），41模型1576012入/18014出、48调用观察。允许文件/809旧行/added0及项目271过1跳过通过；标题29/线29，实际一条自包含doctest用print(active.all(), archive.all())显示两个真实列表。4次修订请求中1次用原verification_ref及精确失败/通过ID成功；替代只补DocTest参数，仍同任务新鲜零退出、未观察副作用，覆盖声明保持未认证。2条前置拒绝未分派且不收费，0清理/权限请求，没有自动改写shell。自然Goal可完成方法修订，不等于其方法认证了全部原要求。

## 独立验收器的表示偏差

预登记v2将doctest每行want解析成独立Python字面量；两个列表经同一次print输出在一行，以空格分开，不能通过这个解析，故初轮v2拒收、当时FormalReview/Accept NOT RUN。原请求没有逐行Python表达式格式限制。该交付的真实输出、数据隔离、MemoryStorage及标题样式都有效；不得将v2的表示假设当用户要求或实现缺陷。初轮v1/v2源码、控制与positive-result原记录保持，不回填通过。

另冻结外部v3诊断，以真实Table.all返回对象在print/displayhook中被展示且doctest输出匹配为依据；不按空格/换行分支，也不改变API返回类型。13旧控制与3新复制控制全部符合预登记期望：同一行真实输出v2拒/v3过，分行真实输出两者过，丢弃真实返回后打印伪造常量v2过/v3未认证。16控制0模型，旧fixture/原件不执行或修改，全部在新复制目录中运行。首次诊断准备缺项目导入路径、0模型未形成判据结果，补baseline导入后完成；v3判据hash保持。

v3是本任务外部审计方法，支持当前实际对象经print或displayhook展示；其他表示只是不被该观察认证，不能从False自动断言实现错误。没有将它接入生产harness、增加通用格式解析器或声称解决任意输出语义。

## 同一正向run的后续正式闭环

确认v2偏差并在执行前补登记新阶段后，v3独立验证当前原件合格（1例）且所有用户文件hash保持，对本次已完成的新run继续正式Review一次。没有重跑goal、修改工件、给在途答案或变更原要求，旧45现场不动；初轮v2拒收与当时NOT RUN仍保留。

最终b1926fb的正式Review38.26秒，6新模型137467入/1882出，4次证据查阅+1次真实局部检查，pass/0.98。它实际检查1条匹配示例；项目271过1跳过来自Goal/结束后的独立测试记录，不能写成Review重新跑了全项目。随后fresh Accept0.32秒，accepted=true、phase=ACCEPTED，原工件和全部Goal执行前缀保持。这是分阶段完整证据，不把auto-finalize、退出0、外部v3或模型评分互相代签。

## 计量、保留与交接

五个初始场加正向后续正式阶段，共55条MiniMax-M2.7记录，1839066输入/22587输出，均有usage，没有本轮新增未知用量或在途预留。正常67调用/观察一一关联且ID全局唯一，65收费/68工具预算单位；含6条controller种子和61条非种子正常观察，2前置拒绝不收费。非种子计数不单凭执行者名称认定方法独立设计或每次选择都来自模型。旧坏件24模型/41工具前缀另计，0模型预检的孤立观察单列，不补账/重编号，不假称所有诊断记录都完整。

initial final/closing/detail审计保存7b初轮结果；后续final-guard-replay、v3-controls、positive-v3-formal、stop审计合并追加阶段，避免把b192调用归为7b。冻结两版源码、原件、基线、45处旧现场hash与原始前缀均保持，新进程组已空；旧DB/待批/旧无进程runningREVIEWED现场、旧1未知在途与4001不变。

私有证据~/.cache/asteria-evaluations/s131-authority-coverage-20261121；工作副本authority-coverage-negative/tables/condition-b-*与原预检condition-bad，日志Windows临时目录asteria-s131-authority-coverage-*。所有新helper/测试/阶段已结束，勿重启或无改重采。私有路由、现场和本机记忆不入Git。

S131正向已在公平审计后完成，旧坏件Review语义误判仍开。下一先核实现有项目验证入口及其来源的可发现性、所选方法对原始适用条件和有效替代的实际覆盖，保留新独立任务与反证控制；不再把固定文档样本无改重采当研发。继续通用harness机制，不放宽授权、不自动改shell、不堆提示/强制工具数或模型、措辞、文档格式专补。Verify禁用时NOT RUN，不启workflow/读key。
