# S74 可复现性审计

日期：2026-06-10
状态：current evidence

## 裁决

S74 的工程基线可复现，但 Week-1 的真实 Beta 矩阵尚不能在干净 checkout 中复签。
opt-in 编排保持默认关闭；不得依据本机 `.asteria`、生成式状态摘要或历史二次描述关闭 S74。

## 已复现

- `python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel`：通过。
- 文档、Execute、Golden Trace、subagent continuation 脉搏：通过。
- `python scripts/s74_beta_matrix_evidence.py --root .`：现在为 evidence-only，快速返回缺失证据，不启动 provider。

## 尚未复现

- 历史文档引用的 `s74_beta_matrix_20260609.json` 与 `s74_subagent_delegation_post_cl010.json` 不在仓库中。
- 当前 checkout 已新增可提交的脱敏 Golden Beta 重复运行摘要；原始 evidence 仍仅保留本机。
- 外部非维护者 Beta friction 尚未形成证据。

## 第一笔 Golden Beta

`validation_small_cli` 显式 live 单槽于 2026-06-10 运行失败：

- 总耗时 `161.729s`
- `3` 次 medium model calls，`0` tool calls，`0` repair
- Coder 首次响应耗时约 `56s`，返回内容未形成有效 ExecutionAction JSON
- smoke 随后自动执行 `recovery-review` 与 `recovery-review-final`，各超时 `40s`

裁决：工具执行不是当前瓶颈；验收观察者不应成为第二恢复控制器。该错误责任链登记为 CL-011 并删除。

### CL-011 删除后配对复验

| 场景 | 结果 | 耗时 | model/tool | repair | Studio/runtime |
| --- | --- | ---: | ---: | ---: | --- |
| small_cli repeat 1 | pass | 26.807s | 2 / 4 | 0 | 1.0 / consistent |
| small_cli repeat 2 | pass | 52.839s | 2 / 3 | 0 | 1.0 / consistent |
| small_cli repeat 3 | pass | 116.229s | 2 / 3 | 0 | 1.0 / consistent |
| doc_update first sample | pass | 108.630s | 2 / 3 | 0 | 1.0 / consistent |

当前判断：默认 Session 主路径跨 small CLI 与 doc update 均可完成；耗时波动主要仍来自 provider 等待。继续扩编排或增加恢复控制器没有依据。

## Golden Beta 三类任务基线

脱敏统一摘要：`benchmarks/s74_golden_beta_summary.json`

| 任务类型 | 通过率 | 耗时样本 | 中位数 | 每次模型调用 | repair |
| --- | ---: | --- | ---: | ---: | ---: |
| small CLI | 3/3 | 26.8s / 52.8s / 116.2s | 52.8s | 2 medium | 0 |
| doc update | 3/3 | 108.6s / 50.3s / 51.9s | 51.9s | 2 medium | 0 |
| context maintenance | 3/3 | 42.3s / 95.4s / 36.1s | 42.3s | 2 medium | 0 |

context maintenance 三次最大上下文估算为 8.5–8.8k tokens，context window ratio 约 4.3%，
每次均 1 次 compact、2 次工具调用、0 repair。当前没有证据支持继续修改 context 或 Runtime 主循环。

### 当前 S74 裁决

1. 默认连续 Session Agent Loop 保持唯一产品主路径。
2. provider 返回等待是当前主要波动来源；作为产品 SLO 与可观测性问题处理，不新增恢复控制器。
3. slim context、bounded loop 与工具执行冻结，除非后续重复 Golden Beta 暴露明确缺陷。
4. subagent、L3、parallel writes 继续 opt-in，不扩大默认面。
5. 下一阶段进入外部非维护者 Beta friction 与 Studio 用户心流验证。

## Studio 与 Friction 边界验证

2026-06-10 当前源码验证：

- Studio production build：通过。
- Session main-path contract：通过。
- user-thread copy smoke：通过。
- interactive main path：3/3 通过，覆盖 Decide、Allow、Cancel 与 Composer 产品动作。
- run-detail smoke 与 beta-workflow smoke：通过。
- maintainer beta trial smoke：通过；workspace switcher smoke 已按 Windows real path 比较，修复短路径/长路径造成的假失败。
- `beta_friction_aggregate`：已有 3 份维护记录，但非维护者样本为 `0`。
- 聚合器已校正：只有明确标记为非维护者的记录才能产生产品 top bucket / DecisionPoint；
  maintainer、restricted-agent sim 与未知身份记录只进入诊断附录。

裁决：当前没有真实 friction 支持新增 Studio 功能。Studio 保持主会话讲用户工作、Inspector
查证证据的现有边界；下一项 Studio 改动必须来自外部 Beta 用户的可复现摩擦。

## 下一阶段唯一入口

1. 组织至少 3 个非维护者 Beta 试跑，覆盖 Goal → Session → Tool → Verify → Result/Continue。
2. 每个试跑记录完成结果、等待感知、卡住位置、是否理解下一步和 Inspector 是否帮助查证。
3. provider 延迟继续作为 SLO 采样；不因耗时波动增加 Runtime 控制器或统一硬停止条件。
4. 只有重复 friction 进入同一桶后，才创建对应 Studio 或 Runtime Slice。

## 下一步

1. 停止重复内部 Golden Beta；现有 9/9 脱敏摘要作为冻结基线，原始运行 evidence 继续留在本机 `.asteria`。
2. 发放 Beta 给至少 3 个非维护者，记录完成率、首次有效工具时间、等待感知、验证结果与 Studio 叙事一致性。
3. 只有重复真实 friction 才裁决下一刀；单个样本先复现，不新增 parser、recovery 或面板尾巴。
4. subagent/L3/parallel writes 保持 opt-in，除非配对任务证明稳定收益。
