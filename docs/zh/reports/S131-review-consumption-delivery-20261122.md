# S131：Review 结论在交付链路中的消费

日期：2026-11-22。基线 `c1d8e56`，修复冻结 `600c51ded3b0b1619bd0d11c5b260eba9d515de1`。修复了评审明细丢失、执行检查通过掩盖评审状态的通用消费问题；没有改模型提示、ReviewAgent、Accept 判定、授权、shell 或编排。旧真实坏件的语义误判仍开放。

## 核实与修复

CLI 的 ReviewResult 原来只给状态/分数，pass 的理由及覆盖明细未传出；最终 Markdown 和 final_report_summary 主要传 review_status。Studio 只读取旧最终摘要，未读取本 run 原生 eval_report；runVerificationHint 又会在执行检查 pass 时提前返回，从而压掉未评审或不通过的信息。原版三个缺评分生命周期控制失败，Studio 六个消费反例全部失败。

新增共享只读 [review_summary.py](../../../src/asteria_runtime/core/review_summary.py)，保留语义状态、原理由、评分来源、原要求覆盖及来源、记录中的执行检查率。缺失或历史非法的数值显示为未评定，不从检查率推导覆盖，不改写原报告或 pass/partial/fail。已记录的模型覆盖不会被投影自动认证为运行时独立覆盖。

Review CLI 文本与结果对象带出这些明细，最终报告和最终摘要使用同一投影。final_report_summary 的 review 为可选字段，两个 schema 副本同步，旧摘要继续可读。run_command 仅追加结果接线，没有顺手重构。原 eval_report schema、模型认知结构及提示均未改。

Studio BFF 读取本 run 原生 eval_report，界面优先消费它，再使用同 run 的摘要投影；评审结论及理由不再被执行 pass 压掉。原徽标改为“执行检查通过”，另明确显示未评审、未评分、覆盖率未评定或模型评估来源。既有 UI 位置和只读证据通路继续使用，没有增加第二套运行时或改权限。

Accept 仍以语义 pass 和候选合并/阻塞条件决定接受，**并不要求评审必须给数值评分**。确定性控制确认 pass + None 可接受，而 partial/fail + 全绿执行检查仍受阻；负控的 skip_review 只避免另起模型评审，不能豁免 pass。Accept 生成的 JSON 摘要和最终 Markdown 保留投影，原评审报告字节不变。没有因“未评分”放松或另加授权门。

## 工程验证

新增 12 个 Python 实例和 10 个 Studio 实例，覆盖缺评分的 pass/partial/fail、未知覆盖与执行率分离、历史非法数量的只读投影、模型覆盖来源、CLI/报告/Accept 生命周期、本 run 原报告优先和 BFF/实际渲染。

- 相关 Windows：138 passed / 42.26 秒；WSL：138 passed / 58.00 秒。
- Studio：279 passed / 47 文件；类型检查、生产构建、Ruff 通过，mypy 棘轮 60 known / 18 gone / 0 新增。
- 定向 ESLint 0 错误 / 11 警告：10 条来自未修改的既有代码，1 条为配置文件未匹配 lint 配置；没有为绿灯压掉警告。
- 真实浏览器控制：1 passed / 4.4 秒，验证执行检查绿与评审未通过同时存在，以及 pass + 未评分/未知覆盖的显示。首次仅在 afterAll 清理发生 Windows EBUSY，等待本测试服务 close 并有界重试后通过。

新测试先纠正了 Windows 文本读取未指定 UTF-8、假设安装了 jsonschema 两个测试问题；改用项目自带校验器，没有安装依赖。构建的包体积提示、npm 本地配置提示和既有 requests 依赖警告保留，不冒充项目新故障。最终完整 Windows **2473 passed / 9 skipped / 42 deselected / 2 warnings / 641.38 秒**，退出 0（控制器耗时 643.54 秒）；两条为既有混合真实/离线路由的测试警告。源码按 600c51d 保持，未借上一轮全套替本轮签字。

## 新自然目标与正式验收

在新隔离工作区运行一次普通 Goal：实现 format_clock(seconds)，拒绝 bool/非 int/越界输入、支持关键字调用、输出单日 ASCII HH:MM:SS，并在 README 说明单日时刻与通用时长的区别及两个示例。只允许 clock.py / README.md 改动，保留原 3 个项目检查、指导及元数据，禁止额外 authored 文件、删除、安装、网络。32 轮 / 外部 600 秒；无控制器种子、无在途答案或工件修改。

Goal **149.70 秒、10 真模型**，1 项任务 done，仅两文件变化，无新增 authored 文件。独立 API 行为 **17/17**（含关键字、边界、类型）和范围通过；README 内容由控制器逐条人工核实，明确单日范围且 0/3661 示例正确，不将它伪装成模型自己执行的检查。

Goal 原生 auto-accept 以执行检查结束，这是已授权的既有行为，**不当作正式语义评审证明**。独立合格后另行正式 Review **11.81 秒、2 模型 / 4 工具**，读取当前 API、README、项目检查并重跑原项目入口，pass 1.00。随后新的默认 Accept 命令 **0.40 秒、accepted=true、0 新模型**；没有 skip-review，复用同一未变产物的评审，不假称再执行独立 17 项。

控制器最初误给 Review 不支持的 --json，原生 parser 在模型派发前拒绝，新增 prepared / ModelCall 均为 0；失败日志另存。随后改用现有文本入口完成上述唯一付费 Review，没有为误用新增 CLI flag 或重跑 Goal。实际 CLI 文本包含原理由和“Requirement coverage: unassessed”。

本轮真模型给出 score=1.00，requirement_coverage=None；最终摘要保留二者不同含义。缺评分消费的可靠证明来自确定性生命周期和旧真实 score99 的只读重放，**不是宣称本轮自然模型触发了缺评分**。

## Studio 消费真实结果

将本次 CLI 原始用户目标及原生 user_progress 经既有 BFF 映射，放入一个新 Studio 展示会话；不伪造执行、模型或检查记录。真实浏览器读取同一工作区的 native eval_report 和 Accept 摘要，显示评审 pass 1.00、原理由、原要求覆盖率未评定，并同时显示“执行检查通过”。两份数据精确一致，原 run 文件 hash 保持，服务/浏览器已关闭。

这是 **CLI 发起 Goal→正式 Review→Accept→Studio 展示**的实证，不是 Studio 发起 Goal 的实证。截图和 API/DOM 对账保留在本机审计，已目视核对；没有把截图或私有现场推送到 Git。

## 计量、保护与后续

合计 **12 真 MiniMax-M2.7 / 12 prepared，232801 输入 / 7912 输出 tokens**，usage 全知、attempt 唯一。25 工具调用 / 观察，23 收费 / 11 加权单位，0 controller seed；两条前置拒绝分别为 run_tests 同时给 command/ref、list_files 读取未授权 checks 目录，未收费，未放宽守卫或改写 shell。9 条循环 trace、83 次引用 / 25 个来源核对同 workspace/run/task/tool、载荷及规范化收据 hash；3 条非循环调用不补 looptrace。这些是装配/来源事实，不证明 wire、内部理解或全面覆盖。

旧 8 个历史声明场与实际 score99 报告零模型重放，语义状态/理由及原字节保持，仅旧非法数值在只读投影显示未评定。103 个旧根、冻结源码、旧数据库/待批/未知预算保持；新进程组在审计时为空，运行产生的 pyc 保留、0 新决定。私有 registration、API/README 判据、stage 日志、计量与 source proof、Studio 截图留本机 s131-consumption-20261122。

下一先核实 Review→Accept 的新鲜性消费：当前工件或目标在评审后改变时，旧 pass 是否被继续使用；同时区分执行后的 auto-accept 与正式语义评审。这里的 fresh Accept 仅指新命令实例复用未变交付，不能代签变化后的版本绑定。先有界复现，再按通用机制修复；不无改复采旧题、堆提示或加模型/措辞/格式补丁，不放宽授权、不自动改写 shell。旧语义失败保持开放。

最终文档控制 23 passed / 1.31 秒。源码冻结以 17 文件精确清单扫描，结果以 6 文档精确清单扫描；完整暂存内容、保护路径和凭据模式检查，私有现场、记忆、截图及过程协议不暂存。Git/远端状态待推送后核对，Verify 若禁用则 CI 保持 NOT RUN，不启 workflow 或配置 key。

修复 `600c51d` 与结果 `2f4049305ae54c7f753e357c782d767c10c8625c` 已推送 origin/main。公开 API 核对结果 SHA 与远端 main 一致，checks=0、workflow runs=0；Verify `267575628` 仍 `disabled_manually`，CI **NOT RUN**，未启用 workflow 或配置 key。此状态另以报告单文件提交，最终 ref 复核存本机审计/记忆，不把本地全套或自然验收当远端绿灯。
