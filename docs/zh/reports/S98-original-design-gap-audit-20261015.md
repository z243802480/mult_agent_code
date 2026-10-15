# S98 原设计缺口对账与 Phase C C7（2026-10-15）

## 核对口径

以 `研发总计划.md` §16.2 的产品主路径 dogfood 和冻结边界为执行真源。逐项把旧设计的意图对照当前代码；“旧文档写未做”不是未做证据。此前 S97 已在 `main@00173d6`，Verify run `38719620460` 三 job 全绿；真实模型 keyed nightly 仍是 `NOT RUN`。

| 原设计项 | 代码核对 | 当前处置 |
| --- | --- | --- |
| IDE 外壳 Phase A/B | `Studio-IDE-shell-重设计方案.md` 自身记录 Phase A 与 B 已落地；`studio/src/styles/layout.css`、`tokens.css` 有全局头部、全幅工作面、评审面宽度 token | **已实现**；工程设计里“下一层待实现”是旧状态，已纠正 |
| Sidebar Search / Workspaces | `features/sidebar/SessionList.tsx` 有搜索框与 all/recent/archived；`App.tsx` 接 `WorkspaceSwitcher`。没有独立 Projects 总览 | **搜索与工作区切换已实现**；Projects 总览仍未做，但没有当前 friction 证据，不列下一刀 |
| C4 隔离→验证→合并 lineage | `features/inspector/EvidenceExplorer.tsx` 的 `lineageList` 已显示三段状态 | **已实现**；旧产品设计“剩余 C4”已纠正 |
| IDE Phase C | 设计方案只记录安全收口一轮；代码中未见通用 `.btn`/`.badge` 原语，`components.css`/`thread-shell.css` 仍分别定义动作控件；头栏密度 C8 未统一 | **部分完成**；本刀完成 C7。C5/C6/C8 与其余视觉收口仍需独立 before/after 评审，不把它们打包成新 Wave |
| Session `fork` | `架构设计.md` §6 已注明设计意图；CLI 命令入口没有 fork，现有 resume/rewind 并非独立探索工作区 | **确实未实现**；涉及会话语义和文件隔离，须有真实 fork 需求再做方向决策 |
| G12 定时任务 | 现有 `TaskGraphScheduler` 仅在 run 内选批，`daily-plan` 依赖外部调度 | **确实未实现**；新增时间触发能力受 P2/ADR 证据门约束 |
| G13 best-of-N | candidate 储存和并发执行可复用，但按 task_id 对账会塌缩，缺自动评审；同 scope 冲突门阻止竞争候选合并 | **确实未实现**；涉及编排冻结与 merge 不变式，不能当作小 UI 接线 |
| G16 LAN/PWA | `studio/server.mjs` 仍监听 `127.0.0.1`，无对外鉴权 | **确实未实现**；鉴权决策先于放开监听 |
| G19 多会话独立工作树 | candidate 在 promotion 后回写共享根；现有跨 run 锁保证串行安全，不提供产物互不可见 | **确实未实现**；需 runtime 侧 per-session 隔离与真实并行需求 |
| G3 置顶与 D5 压缩主线程标记 | 侧栏无 pinned 字段/交互；当前 `ConversationTurn.tsx` 明确把压缩这种机器事件留在 Inspector | 置顶 **未做但无优先证据**；D5 的旧主线程提议与现行叙事原则不符，**不按旧清单补做** |
| 3–5 个真实 Beta 任务 | S93/S94 完整记录了一个小代码任务；此前还有 keyed smoke，但其 `NOT RUN` 远端证据和任务形状不能替代 3–5 个不同真实 Beta 任务 | **验证覆盖未闭合**；下一轮优先扩真实任务样本，再决定是否拉起上列 P2 能力 |

## 本刀实现：C7

`PermissionCard` 与 `DecisionCard` 的 CSS 改为 `surface-1` 中性底、`border-subtle` 外缘、2px 左侧状态色、`--radius-control` 和紧凑间距。已解决权限卡的左缘仍按允许/拒绝分别为绿/红；scope code 早已使用 `--font-mono`，未重复改动。`--permission-bg`、`--permission-border` 仍供等待状态徽章与工具卡使用，予以保留；权限文本和可展开范围原语不变。

浏览器检查使用真实 Studio 页面上的同类卡片 DOM 预览：改前权限卡为 `rgb(30,26,46)` 紫底与 1px 紫框；改后两卡均为 `rgb(19,22,25)` 中性底、2px 左缘、6px 圆角、`10px 12px` 内距。浅色主题中权限/决定左缘分别为 `rgb(107,79,208)` / `rgb(31,116,201)`；320px 宽度下两卡 `scrollWidth == clientWidth`、两个决定选项折成单列。前后截图只留本机临时目录，不纳入仓库。视觉好坏仍需用户主观目视；本刀只证明设计约束、布局和交互没有明显回归。

## 验收与后续

本地验收：`npm run build`、`npm run typecheck`、目标 CSS 的 Prettier、文档契约 23/23、Studio 单测 269/269、hermetic smoke 41/41、Playwright 交互主路径 3/3 均通过。首次并行运行出现事件写入单测 5 秒超时与 smoke 临时目录 `EBUSY`；串行复跑全绿。交互用例初次失败的错误页明确写 `No module named asteria_runtime`，系命令未传 `PYTHONPATH=F:\mult_agent_code\src`；按项目 smoke 环境设置后 3/3 通过。此轮视觉检查用同类卡片 DOM 预览，未触发真实 provider 权限请求，不能据此宣称真实模型链路已验收。

远端验收：[Verify run `38721676522`](https://github.com/z243802480/mult_agent_code/actions/runs/38721676522) 在 `main@a972fc3` 的 Python 3.11、Python 3.13 与 Studio 前端三个 job 全部 success；keyed real-model proof 仍为 `NOT RUN`。

下一项优先按照 `架构设计.md` §10 用不同形状的真实 Beta 任务校准成功率、恢复与体验；若任务实际撞上 G12/G13/G16/G19 再开对应 DecisionPoint。C5/C6/C8 继续作为视觉收口债，不伪装成产品能力缺口。
