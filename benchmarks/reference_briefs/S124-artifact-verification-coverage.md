# S124 — 文档实例的实际验证覆盖

2026-11-11，用户「继续下一项」，承接总计划 §16.2 第 36 项。已读 AGENTS、总计划 §6/§16.2、S123 brief/report。S123 原初轮拒收和外部反馈修复接受分开保留。

## 参考 → 落点 → 不照搬

- [Claude Code 官方实践](https://code.claude.com/docs/en/best-practices#give-claude-a-check-to-run)：提供可运行的判定、读取真实输出再修复；模型判断与强制规则有不同职责。落点：GoalSpec / PlanAgent / AgentHarness 的验证覆盖引导，复用原工具、权限和完成契约。不引入第二个模型代替执行、不为每份文字强制 doctest。
- [Codex-rs 公开基础提示](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md#validating-your-work)：从相关变更的具体检查开始，逐步扩展。落点：按产物声明选择检查，保留必需命令，允许在既有权限内补充有依据的检查。不照搬产品/提供商/具体命令，不靠更严 JSON 判断语义正确。

## 已核实的缺口与最小改动

S123 API/项目测试通过而 usage 声明输出错误；默认隔离 Review 仍 pass/1.0。现有 planning/verification_policy 能保留实际命令，工具失败已有回灌，缺的是对文档实例和声明输出的明确覆盖引导。执行纪律还写着只能运行契约命令，阻碍执行阶段补上已发现的覆盖缺口。

1. 通用提示：目标/规划/执行都要求为产物声明选择实际检查；可执行文档例子验证前置条件、调用和声明输出；普通文字按适当证据检查。保留用户要求及既有 mandatory checks；补充检查限现有读写/命令权限，不凭空安装、越权写验证脚本或替换失败命令。
2. Review：命令通过率不等于产物覆盖率，文件读回/存在不等于语义验证；不伪造 coverage。确定性/缺省评审把未评估的 requirement_coverage 记 null、任务完成率单列；兼容分类继续使用原任务完成信号，不新增空 coverage 闸。保持原 score/status/预算/完成闸，澄清理由与模型评审提示。
3. 不加 TinyDB/模型/错误词分支，不硬编码 doctest 自动执行，不改 execute/run/acceptance 栈或提高预算权限。

## 验收与真实采样边界

先跑相关回归，再完整 Python/类型/Ruff/离线基准。新增检查器须用真错误/正确文档验证，而非只断言提示词字符串。

真实采样：在 S123 初轮产物的全新副本（不带 .asteria）提出仅审核修正文档的目标，不提示具体错误位置/正确计数，不给现成解法或失败检查器。保留原代码/测试，真实 RunCommandTool 同环境预检，冻结输入/执行器后再调用；默认 profile、同一 provider，原权限/预算，外部上限 900 秒，一个新目标。观察模型是否自行执行文档示例并处理真实失败；若没有，不称引导已被证明有效。独立验收检查文档真实输出、源码/工具范围和账本；通过才正式 Review→Accept。原 S123 不变，样本不重跑刷绿，不外推小时级/provider 通用可靠性。

S123 当前精确提交 2a44d8e 的 CI 43035370303 为失败：Python 双版过，Studio 浏览器依赖 Ubuntu 镜像 DNS 失败，UI 未运行；不以此声称产品全绿，不在本刀顺手改 workflow。
