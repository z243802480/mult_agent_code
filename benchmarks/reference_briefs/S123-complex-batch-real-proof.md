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

## 初轮后的文档审计诊断

冻结 API oracle 14/14、旧 readonly 20/20 与完整项目测试均过，但人工审阅发现 usage 示例两次插入却标 inserted=1。原初轮保持未验收，不做正式 Accept，不修改其代码或文档。用标准库 doctest 在实际工具环境核对新增示例；另允许在隔离的源码/运行状态副本上调用一次默认 Review 作诊断，不提供错误位置/答案/新增检查结果给模型，核实既有评审能否自行发现。保留原 run/源码/账本哈希，诊断计量单列、不重置克隆预算、不替换初轮结果。后续修复依据证据再定，不直接改模型的原产物。

## 外部反馈修复诊断（单列，不替换初轮）

doctest 五次尝试一处失败；默认隔离 Review 仍 pass/1.0，原 run 字节不变。追加一次普通文档修复目标：从初轮 SOURCE 复制不带 .asteria 的独立副本，给出实际验证失败和公开标准库示例检查器，只允许修两份文档、要求两者有可执行示例，API/原测试/检查器不改。此为外部反馈辅助、新 run，不称初轮自治或同 run 恢复；原初轮继续拒收。诊断单独记账，原 72 次与隔离 Review 1 次不重置，原+诊断合计上限 200 次模型；文档修复外部上限 600 秒，原目标 1800 秒不变且不混加耗时。仅通过公开检查与源码隔离审计后报告修复，不人工改模型文档；不增 Runtime 能力、token 上限或权限。

反馈修复调用前登记：公开示例检查器基线红、完整 271 tests 绿；新 run 的实际档位以 registration.json 为准，输入 SHA256：

- VERIFY_EXAMPLES.py: bfe013a778c8d15f063fd64b5ba5747d033183a1aceb9c7c0a21c531c90a8ec5
- goal.txt: 42564efaaff886748cbbacb026ac3f68aa4114dbd4900a43226844f0a253263d
