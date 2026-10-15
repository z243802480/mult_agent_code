# S92 — Studio 真模型证据进入 release 摘要

## 目的

把 S91 已接入 nightly 的 Studio keyed real-model job 纳入 release 的可见摘要，
让发版人知道默认分支是否有 Studio 证据。此刀只做可见性，不把 Studio 结果变成
release 硬闸；没有 run、缺 key 或失败都必须原样标出。

## 设计边界

- 查询默认分支最近一次 `nightly.yml` workflow run，再从 jobs 中定位
  `studio-real-model-nightly`。
- 旧 nightly 没有该 job 时显示 `NEVER RUN`，不能把旧 mcp/ring job 的绿色冒充 Studio 通过。
- 以 `Studio real-model smokes` **步骤**是否真的执行且成功为通过条件，不能只看 job 绿色：缺 key 时 smoke 步骤被跳过，但记录 `NOT RUN` 的步骤成功会让 job 仍是绿色。
- smoke 成功显示时间和 run 链接；失败显示 FAILED 和链接；skipped 显示 NOT RUN，取消或读不到证据显示 NOT GREEN/UNKNOWN。
- 该 job 只产生 Summary，不失败退出；`build-release` 可以继续，硬闸留待真实连续证据后另行决策。
- 同一轮证据核对发现 runtime ring nightly 也存在“绿色 workflow + 被跳过的真模型步骤”。共用步骤级判定修复 `real-stack-proof`：真失败仍阻断发版，缺 key 的 `NOT RUN` 继续诚实放行。

## 验收

- release workflow 具备 actions read 权限与独立 Studio proof job。
- 解析 old/no-job、success、failure、other conclusion 四条路径。
- 用真实 GitHub run `38676431024` 的形状钉住“绿色 job + 跳过 smoke ⇒ NOT RUN”。
- workflow YAML 结构检查通过；不调用 provider、不新增重试。
