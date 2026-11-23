# S131：Review 输入绑定与当前批准的有效性

日期：2026-11-23。基线 `843ccaee`，首修 `9d99223edfbd3bd56d4ee0264a21160545ff0594`，最终工程冻结 `a61bb41c248221ae2c2656c965daa957ebb694c7`。本刀修复评审后输入变化仍沿用旧 pass 的通用消费问题；旧真实坏件的语义误判仍开放。

## 核实与实现

原版隔离控制 5 红 / 1 绿：工件、目标、任务、指导在评审后变化仍可被 Accept 接受，评审中工件变化仍签 pass；仅修改 mtime 的控制原本正确。

运行时在 Review 开始捕获同 run/snapshot、goal_spec、task_plan、声明工件、根 AGENTS 的内容绑定，并复用 ReviewTools 已有 manifest 加入被检查依赖。绑定由 Runtime 产生并校验独立 schema，不要求模型填写。消费时比较实际内容；变化、无法安全读取、绑定不全或历史未绑定都不能继承当前批准。保留原报告的状态、理由、未知分数和覆盖来源，另给 freshness/effective_status，不改写历史报告。

Accept 的 skip-review 不能跳过新鲜性。候选晋升前后及最终接受前核对，默认路径可沿既有 Review 对变化后的交付重新评审；内容完全恢复时可复用同一绑定，仅 mtime 变化不误失效。CLI 状态/最终报告与 Studio 同时消费当前有效性，Studio 区分历史 pass 和当前已过期，并撤去标记完成入口。

绑定有文件数/字节上限，拒绝保护路径、链接和越界读取，捕获窗口消失也不签有效。此处只绑定已知输入及已观察依赖，不覆盖任意新增文件、完整目录成员、未观察依赖或环境变化，不认证需求语义覆盖，也不是防本地同时篡改报告与绑定的签名机制。Studio 遇当前保护策略中不支持的字符类模式会安全降级 unavailable。没有改变 ReviewAgent、模型认知 schema、提示、权限、shell、预算或编排。

## 工程验证与回归修订

新增 26 个 Python 实例（含后补的离线模拟变更反例）、12 个 Studio 实例。首修相关 Windows 74 过 / 1 skip、WSL 75 过；Studio 291 过、类型/构建通过，受控浏览器 1 过 / 5.2 秒。首浏览器失败来自旧展示 fixture 缺 task_plan，补测试元数据后通过，没有放宽守卫。

首修全量 **7 失败、2490 通过、10 skip、42 排除，687.36 秒**，原日志保留。五项旧测试在晋升改变工件后继续用旧 pass，现显式评审当前交付；两项既有离线 band 生成无绑定合成报告，窄修其 fixture 生成器，明确标注模拟来源且候选内容不变。新增反例证明模拟工件变化仍被拒绝。没有为通过而修改 FakeModelClient 或通用新鲜性判据；模拟结果不是模型评审/自主修复的证据。

最终工程冻结相关 Windows **66 过 / 1 skip**（含 23 文档控制）、WSL **44 过**；完整 Windows **2498 过、10 skip、42 排除、2 既有 warnings，604.45 秒**，exit 0。Ruff src/tests/scripts 通过，mypy 棘轮 60 known / 18 gone / 0 new。最终冻结未再改 Studio 源码，其 291 项与浏览器/类型/构建结果仍对应同一实现。

## 新真实流程与反例

新私有标准库项目实现 normalize_tag，仅 tags.py/README 可改，保留原指导、元数据与 3 项浅检查；32 轮 / 外部 600 秒，一次自然 Goal，未给模型外部判据或在途答案。**191.88 秒、19 真模型、2 任务 done**；仅允许的两文件变化，0 authored 新增，独立 **23 API**、人工 README 和范围核对通过。

模型自发修订过一次有缺陷的规划验证方法，原失败保留；4 次权限前置拒绝没有收费或放宽守卫。正式 Review **18.67 秒、2 真模型 / 5 工具**，结论 **pass，score=None，覆盖率未评定**；原 3 项项目检查通过。默认 Accept **0.41 秒、accepted=true、0 新模型**。本轮真实触发了未评分的 pass，没有强迫模型缺分或按工具数评审。

之后原生进程退出，由控制器明确制造反例，不混入模型行为：

| 状态 | 独立观察与消费 |
| --- | --- |
| 将工件替换为实际错误实现 | 23 API 全失败；skip-review/no-promote Accept 0.40 秒拒收，effective unknown，指明 tags.py 变化 |
| 工件原字节恢复 | 默认 Accept 0.41 秒通过，0 新模型 |
| 原目标字段增加适用条件 | skip-review/no-promote Accept 0.43 秒拒收，指明 goal_spec 变化 |
| 原目标字节恢复 | 默认 Accept 0.42 秒通过，报告 hash 与原件一致，0 新模型 |

这些恢复由控制器完成，不是模型自主发现、修复或新语义评审。五次 Accept 合计 0 新模型，不按未变代码重复采样。零模型重放 8 个旧报告：原状态/理由/原字节保持，未绑定的当前有效性为 unknown。

初状态辅助脚本误传不支持的 --session-id，parser exit 2 / 0 模型，错误保留。另登记零模型读取控制：临时重放同一已记录错误字节，仅执行支持的 status --json 后 finally 恢复。真实 payload 为 ready_for_review、can_accept=false、can_review=true、next=review。控制器后置断言先误读不存在的顶层字段、又把顶层 hash 与递归集合比较，均在保存的 payload/hash 上修正，没有重复 CLI 或付费阶段；66 个原 run 文件及模型账本保持。

## Studio 与来源对账

上一轮私有展示桥将 run/session 参数传反，旧 API/截图不能认证严格会话归属，已在原报告追加更正；旧私有原件不动。本轮两个全新展示会话使用正确 event/session/run 顺序，分别 **1381 / 1384** 条原生 progress 映射逐条核对身份，浏览器均实际消费预期 run API；原 eval_report 精确相同，原 run 文件 hash 保持。

当前场显示“评审通过、评分未评定、原要求覆盖率未评定”；错误工件场显示“历史评审通过，当前输入已变化，评审已过期”，且无标记完成按钮。截图已目视，浏览器和服务已关闭。仍是 CLI 发起后展示原生证据，不冒充 Studio 发起 Goal，不伪造模型/工具/检查记录。

合计 **21 真 MiniMax-M2.7 / 21 prepared，497144 输入 / 12531 输出 tokens**，usage 全知、attempt 唯一；45 调用/观察、41 收费 / 23 单位，0 controller seed。18 条循环 trace、173 引用 / 37 唯一来源 ID 核对同 run/task/tool、载荷及规范化收据 hash；3 条非循环不补 trace。这是装配来源事实，不证明 wire、理解或全面覆盖。虽配置警告提示未使用的 cheap 档为 fake，本场实际 21 条调用全为 MiniMax；没有以配置警告或预期路线代替调用审计。

106 个旧根、冻结源码、旧数据库/待批/未知预算保持；新决定 0，所有原生付费进程已结束。私有 registration、外部判据、原日志、阶段结果、计量审计、截图与 protocol 留本机 s131-freshness-20261123，不提交私有现场、记忆或凭据。

## 后续边界

本刀不关闭旧 RST 标题 29 / 线 28 的语义漏判。新的真实摩擦：方法已修订且当前检查通过，最终验证汇总仍累计历史失败而显示 22/23 failed；过期 Accept 的推荐命令仍为通用 debug，Status/Studio 则指向 Review。下一先核实这两条消费责任，区分历史失败与当前检查、正确给出重新评审入口，按证据修复；不删旧失败，不把方法通过等同原要求全面覆盖，不扩大扫描/授权或加提示/专用补丁。

主修 `9d99223`、fixture 修订 `a61bb41` 与结果 `0978f51aa32a8e9c8554868d5b528f174bf59a94` 已推送 origin/main。公开 API 核对结果 SHA 与远端 main 一致，checks=0、workflow runs=0；Verify `267575628` 仍为 `disabled_manually`，CI **NOT RUN**，未启 workflow 或配置 key。远端记录以报告单文件提交，最终 ref 复核留本机 protocol/记忆，不把本地测试和自然验收当远端绿灯。
