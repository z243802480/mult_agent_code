# S99：文档任务的真实 Studio 主路径

日期：2026-10-15。参考切片：`benchmarks/reference_briefs/S99-beta-task-variety-dogfood.md`。

## 实跑与结果

在两个隔离的本地工作区，用 Studio 的 Goal 入口和本机现有模型路由执行同一个 `doc_update` 任务：按 `docs/flow-notes.md` 更新 README 的使用流程，保留 Setup，只改 README。真实调用前 `model-check` 的配置与调用均成功。工作区分别位于系统临时目录 `asteria-s99-doc-chq6o73q` 与 `asteria-s99-doc-retest-x79_xojh`；仓库未收录路由或密钥。

| 轮次 | 原因与实际行为 | 结果 |
| --- | --- | --- |
| 首轮 | 模型生成的 GoalSpec/Plan 擅自把 `grep -A5` 当作验收命令；Windows 主机无法执行，虽然 README 内容符合要求，验证记录仍为 3/4、失败 1 项。约 4 分钟，16 次模型调用、13 次工具调用。 | Review 不能宣称完全通过；原始运行保留未 Accept。 |
| 修复后复跑 | GoalSpec/Plan 明示主机 OS，要求可观察的验收条件，文件内容检查优先用文件工具；模型只读 README/说明、写 README、搜索回读，没有再编造 shell 命令。约 2 分半钟，10 次模型调用、7 次工具调用（含后续 Review/Accept）。 | README 的 Setup 原文保留，含 Goal→Review→Accept、验证证据及受阻说明；验证记录 2/2 通过，但没有可执行测试命令。Review 通过，浏览器点击 Accept 后 `run.json` 为 `completed / ACCEPTED`。 |

第二轮 README 内容由仓库外的独立检查核对：只改 README，Setup 保留，目标四项文字均存在。Review 的“通过”指内容回读与结构化检查；`verification_command_count=0`，不能说通过了自动化测试。首轮 `grep` 失败被留在证据中，没有伪装成成功。

## 真实用户路径发现的 Studio 问题

Review 后 `/api/diagnostics.workflow.can_accept=true`，但运行详情的 `main_action.next_command` 仍为 `review`。原按钮写着“标记完成”却把这个过期命令提交给服务端，因此会再跑一次 Review。按钮现在固定提交 `accept`。同时，任务结束后 Studio 原先没有刷新工作流状态，卡片会停在旧的“查看”；现在运行态转为空闲时刷新 overview、diagnostics、该 run 证据与改动状态。浏览器实测无需页面重载即可从 Accept 进入终态，卡片消失，线程显示最终交付记录。

回归覆盖“诊断允许 Accept，但运行详情仍建议 Review”的组合，断言 POST `next_action=accept`。交互 Playwright 4/4；Python 相关测试与文档契约 45/45；Studio 单测 269/269；Studio build/typecheck 通过。hermetic smoke 首轮 40/41，唯一超时的 `chat-lifecycle-smoke.mjs` 单独复跑通过，完整套件随后复跑 41/41。远端 Verify 尚待提交后核对。

## 后续

这仍只覆盖第二种任务形状；样本量不足以估计总体成功率。下一次从 `benchmarks/beta_user_tasks.json` 选择静态网页或跨文件修复任务，继续记录真实运行和恢复。G12/G13/G16/G19 尚无触发证据，不据此开新功能。远端 keyed nightly 未配置时维持 `NOT RUN`。
