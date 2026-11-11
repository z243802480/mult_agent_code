# S116 — 新版读取反馈的独立真实目标

2026-11-11 用户「继续下一步研发计划」，承接总计划 §16.2 第 28 项。已读 AGENTS、总计划 §6/§16.2、S115 brief/report、本机记忆及独立仓库协议。

参考：[cachetools 官方文档](https://github.com/tkem/cachetools/blob/ca7508fd56103a1b6d6f17c8e93e36c60b44ca25/docs/index.rst) 的公开淘汰策略、可定制 timer 与显式 expire；[Anthropic 工具工程](https://www.anthropic.com/research/writing-tools-for-agents) 的真实任务评估与有界反馈。本刀通过公开 API/未来淘汰结果和测试自持的计数器观察副作用，不规定私有字典/链表布局，不复制 upstream/private 实现。

## 冻结范围

- 执行器：`f4311536b3f30026964a676475de338e2807a39b`，只导出 src/schemas（已通过完整 1669 与精确 CI）。不把本仓库测试、oracle 或旧解答放到执行器。
- 全新上游 cachetools v6.2.1，commit `ca7508fd56103a1b6d6f17c8e93e36c60b44ca25`，MIT；归档 SHA256 `74a81ab41704515b4c33c87f01e5db3ad024ac24653a0472715b6745567aca33`。选择明确可在已有 Python 3.12 环境验证的冻结基线，不假称最新版。
- 新公开目标：为标准 Cache 家族提供不扰动读策略/过期存储的 peek / peekitems 检查接口，更新文档与新增回归，保留原测试与配置。完整公约与独立 oracle 在模型调用前另行落盘并固定哈希。
- 目标、冻结执行器、外部控制器/oracle 分目录，保留原许可证及输入哈希；无上游解答、安装包源码、相邻实验、运行时源码读取。正常 Python/pytest 与来源绑定允许，不装依赖。

## 运行与验收

一次普通真实 goal，auto 权限与现有真实路由；外部时限 3600 秒，原预算不提高。本轮不安排人为暂停，不干预解题、不临时更改 oracle、不追加失败重试刷绿。不强制 read_file、搜索或 shell 的选择：事后分别记录 next_offset / partial_line 是否出现及其后是否采用对应 offset，未触发就写未触发，不冒充机制已实证。

验收先跑原全套+模型新增测试、固定独立 oracle，校验允许范围、原输入/执行器哈希、来源绑定、真实路由和完整工具输入审计，再正式 Review→Accept。默认 auto-accept 不替代独立验收。检查器本身须通过代表性合法表示/坏副作用反例，不再依赖产品返回测试私有属性。

若暴露通用 runtime 缺陷，先确定性复现再窄修；不把模型认知写死到按题目/模型名/错误词补丁。改产品代码才跑相应完整检查与精确 CI；仅新实验/文档复用未变生产 SHA 的 CI并跑文档/检查器回归。每次原失败保留，真实未完成仍未验收。收尾更新计划/ACTIVE 与本机记忆；小时级/独立 provider 可靠性与 keyed NOT RUN 的边界不变。

预调用冻结：公约 SHA256 `42c0baf4c91a8f4a2cda27708750e6177a79fc4f9c900b2ce5ccf7d5aca3c49c`；oracle `f06d1df37efa1b2a7cf7a1576b71a1ae6f6e25b03dbdbaca5bd4056907b0e10e`。干净基线原测试 220 passed；oracle 15 方法因缺新 API 为红（53 个 subtest ERROR）。检查器自身 8 项/文档 23 项过。目录分别为 s116-cachetools / s116-f431153 / s116-cachetools-20261111；目标执行完先外部检查与人工读取审计，再正常 Review/Accept，不提前自动执行独立接受。

## 真跑后的通用边界修复（不重跑原样本）

目标已在 f431153 上独立 15/15 + 264 tests 通过并确定性 Review/Accept。补审发现两次 read_file 在 registry 前被 task read_scope 拒绝、未进入 tool_calls，且与随后执行记录重用 ID。原 task 的 whole-session read_scope=[] 被 execution_preferences 的目录提示并集错误变成有限集合（其中还含路径样式的普通说明）。不能把此轨迹说成模型从未尝试 read_file，也不能归因成纯工具偏好。

允许先确定性复现再窄修：①空 read_scope 原意是工作区内不设该层读取门，合并额外目录提示须保持这个原意；有界 scope 的原范围/显式新增目录仍按既有规则，PathGuard/秘密/越界及写权限不变，不按 AGENTS/TASK 文件名特判。②registry 前本地门禁拒绝通过既有 record_tool_call 记 denied 尝试，下一 ID 正常递增，真实 registry 已有记录不重复，原执行预算不虚增。对语义及审计各加正反例与真实 gateway 回归。原实跑不因修复而重新采样/改 oracle；新版工程修复单独以 Windows/WSL/精确 CI 验收。

最终回执：真实目标 171.82 秒、15/15 + 264 tests、确定性 Review 1.00→Accept；原轨迹有 2 次未入调用账本的 read_file 拒绝，0 成功读取/0 提示触发，已纠正统计。c29c55c 两处通用修复经旧版 4 红 1 绿→新版相关 Windows 79 / WSL 56、完整 Windows 1682 通过，Verify 42969469061 三 job 全绿；不重跑原样本或改 oracle，工程修复无新增真模型采样证明。完整事实、边界及下一步见 `docs/zh/reports/S116-independent-cache-inspection-20261111.md`。
