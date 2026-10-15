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

## 推送后 CI 复核（2026-10-15）

- `main@0f5802b` 的 Verify run `38677142768` 三个 job 均红：Studio 停在 Format check，Python 3.11/3.13 停在 Verify 步骤。此红灯先于 release 验收，不能据本地 29 个相关测试代替全量 CI。
- 本地按 LF 规范化逐文件运行 Prettier，找到 21 个真实格式差异；只格式化这些文件。另以 Ruff 定位两个被跟踪的 Python 违规：路径引导后的延迟 import E402、未用 import F401。修复后重新推送 Verify，按远端结果再判断是否收口。
- provider key 的 Actions 配置仍不可由此切片推定为已完成；现有 Studio/ring smoke 都是 `NOT RUN`。
- 复验 `da07df1` 的 Verify 继续红：Studio 已越过 Format check，停在 `Studio smokes`；Python 3.11/3.13 仍停在 `Verify`。公开 GitHub API 只暴露失败步骤，日志需登录；因此在 Verify workflow 中于失败时把末段输出写为 Actions error annotation，同时保持原始失败 exit code。该摘要不包含 provider key，因为 Verify 路径不接入真模型密钥。
- `8756aeb` 的 annotations 给出真因：Studio 39/40，唯一失败是 G7 快照 smoke；在无全局 Git identity 的环境复现 `commit-tree` 报 `Author identity unknown`，给 Studio 自有快照固定 identity，并让 smoke 清空全局 identity 钉住回归。Python 失败是 mypy ratchet：历史 baseline 按 Windows 产生，Linux 把 Windows ctypes 名称当新债；此外本机缺 mypy 时 ratchet 曾将 exit 1 + 空 stdout 误判为 0 错误。固定 Windows 3.11 类型目标、缺 mypy 时 fail loud，并修 6 个与平台无关的新类型错误；baseline 不扩张。待远端 Verify 复验。
- `6b4c365` 的 Verify run `38679750093`：Python 3.11/3.13 **通过**，Studio 通过 smoke 后停在 UI tests。继续将 UI 失败尾段写成 Actions error annotation（不改变 exit code），再按新日志修具体断言。Windows 本地 UI 有 5 项红，其中 4 项是本机未安装 runtime 的 `init exit 1`，不能推成 Linux CI 同因；另 1 项待远端比对。
- `27ebf53` 的 Verify run `38680150659`：Python 两档仍绿；Studio UI 8/12，4 个 model-pin specs 均 `spawn python ENOENT`。代码中 `new URL(import.meta.url).pathname.slice(1)` 把 Linux 绝对路径首个 `/` 去掉，使 spawn 的 `cwd` 不存在；改用跨平台 `fileURLToPath(import.meta.url)`。本地以 `PYTHONPATH=src` 跑该 spec 4/4 通过；远端待复验。
- `c27abca` 的 Verify run `38680540072` **整体 success**：Studio、Python 3.11、Python 3.13 三 job 全绿。S92 代码与离线门已验收；release workflow 尚无该提交的手动运行，且双 key 的 Studio/ring nightly 仍未实际执行，因此 release 中的真模型状态仍应是 `NOT RUN`。

## Release 真跑验收（2026-10-15）

- [Release run 38688770468](https://github.com/z243802480/mult_agent_code/actions/runs/38688770468) 在 `main@c6cdab7` 手动触发并 **success**：可复用 Verify 的 Studio、Python 3.11、Python 3.13 三个 job 均通过，两个 proof job 与 `build-release` 也通过。
- 两个 proof job 的真实日志分别报告 `Studio real-model proof: NOT RUN` 与 `Real-stack proof (ring-recovery): NOT RUN`。所读 [Studio nightly 38676431024](https://github.com/z243802480/mult_agent_code/actions/runs/38676431024) 和 [ring run 38639068136](https://github.com/z243802480/mult_agent_code/actions/runs/38639068136) 的 keyed smoke 步骤均为 `skipped`；Studio 日志明确提示未配置 provider key。Release 的绿色不代表真模型通过。
- `build-release` 日志列出 `asteria_runtime-0.2.0a2-py3-none-any.whl`、`asteria-studio-0.2.0a2.zip`、`asteria-beta-0.2.0a2.zip`、`SHA256SUMS.txt`；Actions 上传了 `beta-release-assets` artifact（ID `11952015699`）。本次 `workflow_dispatch` 未创建 GitHub Release。
- S92 的远端工作流验收已完成。仍待有双 provider key 的 nightly/ring 真实运行；此前不得把 keyed 路径标成 PASSED。
