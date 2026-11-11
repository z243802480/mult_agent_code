# S123 — 更复杂真实目标与恢复证据

2026-11-11 用户「继续」，承接总计划 §16.2 第 35 项。已读 AGENTS、总计划 §6/§16.2、S122 brief/report 和本机交接。保留此前失败与未运行证明；不恢复 S121 的安装 decision。

## 参考与约束

复用 S121/S122 已验证的显式意图、[结构化模型输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)参考、同身份验证、实际环境预检与独立验收。执行器固定产品 `6e3be93`（Verify 43008738110 绿），无新产品补丁的证据前不改 Runtime。模型负责设计、验证与修复，外部控制器只执行预检/观察/验收，不供解法、导航或中途修代码。

## 新目标与复杂性

在 S113 已接受 TinyDB readonly 源码产物的独立新副本中实现 `TinyDB.apply_batch(operations, *, dry_run=False)`：输入先完整验证再 IO；put/remove 跨表顺序处理，计数/重复目标/缺失目标语义明确；有效批次一次读、至多一次写；全量 staging 深拷贝，异常不泄漏内存改动；dry-run/readonly 不越权；成功提交后已有表句柄查询与下一 doc_id 不陈旧，JSON/custom storage 和旧功能保留。不是 S120 快照重跑，不使用其解法或 S121/S122 目标源码。

必需改动：tinydb/database.py、docs/usage.rst、docs/api.rst、NEW tests/test_apply_batch_s123.py。允许非必需：tinydb/table.py、tinydb/__init__.py。可选实现：NEW tinydb/_batch.py。其它源码/所有旧测试/配置/LICENSE/AGENTS 与公约不改。行为细节按单独公开公约；独立 oracle 只用公共接口和 evaluator 自有 storage 计量，不把私有布局当语义。

## 验证顺序与停止条件

首次真实调用前，公开 pytest/源码绑定、原 readonly oracle、完整旧测试均须经真实 RunCommandTool 在同一 Runtime 父环境通过；新增 API 基线红。公开验证命令显式声明项目导入条件，禁止控制器额外 PYTHONPATH 偷渡。先核对检查器正控制与错误实现反例、实际默认 profile，随后冻结全部输入/执行器哈希并提交登记。

本轮一个真实目标，1800 秒外部上限，既有模型/工具/迭代/repair/replan 预算和权限不提高。不造失败、撑时间、强制工具或档位、迁移旧会话、安装、访问网络/秘密/其它实验/执行器或安装包实现。观察自然协议纠正/工具错误/测试修复/重规划；未发生不能冒充恢复证明。初始输入/检查器在调用后不改，原样本不重跑刷绿。

独立验收包括新旧行为、同身份公开命令、严格文件集合、源码绑定/来源与执行器哈希、全部工具输入/唯一观察 ID、typed 产物语义与实际原计划、累计计量。单独审模型自写测试有无迫使代码偏离原需求；整体通过且 native completed 后正式 Review→Accept。失败保留，通用缺陷先确定性复现才窄修，不代修模型产物。只改验证资产/文档时复用未变产品完整 CI，新增判分器/文档在 Windows、WSL 验证；产品变动才完整复验。

收尾更新唯一计划/ACTIVE/记忆，明确本次实际耗时/档位/provider，不能把一个更复杂但分钟级目标外推小时级可靠性；keyed proof 仍 NOT RUN。

## 首次调用前登记

实际工具同环境预检：原 236 tests、公开绑定和 readonly oracle 20/20 绿，新 API 基线红；独立 oracle 14 方法正控制绿、过量写入反例被拒绝。0 模型调用，源码/执行器哈希未变；实际 profile=harness（Harness profile required (high_risk).）。执行器固定 6e3be93260d24beca2d27c4af02b48d30b52625a。输入 SHA256：

- contract.md: 6fac5acf9d8584504d01eeec5776733dfebd56e499dc492444b428aaff6ee038
- goal.txt: 3e97339f9d6411adf735c21dceeb90e803925b33d431dda81c78cc295b6fcb36
- tinydb_apply_batch_oracle_s123.py.txt: 778d9315351f8ed5f351e5abf4c376645815eab72f8b6963ec08cd932b985514
- tinydb_readonly_oracle_s113.py.txt: 9e282df69c7994c821a0786a69be476f373d13e1eb0dd521b0859af620395788
