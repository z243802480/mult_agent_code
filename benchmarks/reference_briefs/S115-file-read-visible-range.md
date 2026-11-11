# S115 — 文件读取可见范围与续读提示

2026-11-11 用户「继续修正吧」，承接总计划 §16.2 第 27 项。已读 AGENTS、总计划 §6/§16.2、S114 brief/report 与本机记忆。当前基线 aa3e4f0 / main a94ab2a；S114 的评审去重与原实验结论保持。

参考：[Anthropic 官方工具工程](https://www.anthropic.com/research/writing-tools-for-agents) 推荐有界输出、分页与明确可操作的截断反馈，而非让模型猜测遗漏内容。本刀沿用已有 read_file offset/limit、PathGuard、原始 ToolResult 与模型观察通道，不新造文件读取 API，不按模型/任务补丁。

## 已知证据与范围

S113 179 次读取中 40 次 payload 字符截断；offset=390 已证确从 390 行开始。缺口在 `_model_facing_payload`：标题使用 requested line_end，随后再按字符剪裁，导致模型看到的行少于标题；小文件无 line_end 时会显示 None。不能据此声称全部重复读取都有相同成因。

1. 先确定性复现：整文件缺 line_end、大窗口被字符截断、非 1 起点、长单行、底层字节截断、未知总行数、空文件/越过末尾。
2. 只修模型可见 read_file 反馈及必要工具说明：标题按实际可见行计算，完整行优先；输出整体保持 6,000 字符上限；有后续完整行时给 1-based next_offset，不跨过未显示的行。
3. 超长单行或底层字节截断的尾行必须说明部分可见，不能冒称该行已完整读取，也不能给跳过其剩余内容的续读指令。不反复提示缩小 limit 能恢复同一长行的剩余字节；引导使用适当的可用工具定点查看。
4. 不改原始 content、实际 offset/limit 语义、保护路径、权限、预算、验证判据、持久化 schema 或 execute/run。S114 Review 投影须继续保留只有 payload 才有的文件内容；旧 payload 不能因 renderer 升级而误删。

## 验收与交接

正反例 + 从真实 ReadFileTool→observation→模型 feedback 的测试；按 next_offset 遍历大文件时无漏行/重叠，输出有界。Windows/WSL 相关与完整必要回归、Ruff/mypy ratchet、精确 CI；更新总计划/ACTIVE、报告和本机记忆。纯工具协议修复不以重复真模型采样刷绿，不宣称已经减少自主调用数或证明小时级可靠性。原六批未跟踪输入、原实验账本、私有 key/routes 不提交。

回执：本刀已验收，旧版 10 红→14 新实例过；Windows 完整 1669、相关 Windows/WSL 各 95、文档 23 通过，Ruff / mypy ratchet 无新增，f431153 的 Verify 42953846909 三 job 全绿。700 行/9 页真实工具链无漏重，原文件 hash 不变、每页 ≤6000 字符；长行明确 partial 不跳过未读部分。未新增真模型自主样本，下一刀独立真实目标观察提示采用。详见 `docs/zh/reports/S115-file-read-visible-range-20261111.md`。
