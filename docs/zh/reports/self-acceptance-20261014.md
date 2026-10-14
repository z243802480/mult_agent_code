# 2026-10-14 自验收报告

## 范围

验收基线：`main@5ce4e6e`（S91 Studio 真模型 nightly 接线）。本报告区分本机可复现结果、
CI 等价结果和仍未取得的远端证据，不把旧 nightly 结果挪作 S91 证明。

## 已通过

| 检查 | 结果 |
| --- | --- |
| Python 全量 `pytest -q` | **1507 passed, 3 skipped, 38 deselected**；2 条既有 UserWarning |
| 文档契约 | **23 passed** |
| Studio Vitest | **262 passed / 42 files** |
| Studio TypeScript | **通过** |
| Studio production build | **通过** |
| Studio hermetic smokes（`PYTHONPATH=src`） | **40/40 passed** |
| Studio keyed real-model smokes（同一提交的本地验证） | intent routing、plan output、route worker **3/3 passed** |
| Git diff 检查 | **通过** |

## 代码状态

- S91 nightly job 已接入：双 key gate、三条 keyed smoke、`NOT RUN`/`FAILED`/成功摘要、日志 artifact。
- 预览代理 websocket 预期断连已收口；回放导出 smoke 已隔离桌面过滤器注入噪声。
- 当前提交已推送到 `main`；工作区剩余文件均为既有未跟踪验证产物，未进入提交。

## 未完成证据

- GitHub Actions 尚未出现基于 `5ce4e6e` 的 S91 nightly run；最近旧 run 只执行 `mcp-official-smoke`。
- 因此尚不能宣称 Ubuntu + 真 provider 的 Studio nightly 已通过，也不能把 Studio 结果接入 release 硬闸。
- 本机 `npm ci` 报告 13 个依赖审计问题（2 low、2 moderate、7 high、2 critical）；本次不升级依赖，避免把 S91 变成无证据的依赖迁移。
- Studio lint 有 47 条既有 warning、0 error；本次未把 warning 伪装成清零。

## 下一步

等待或手动触发 `nightly.yml`，只处理基于 `5ce4e6e` 的真实结果：通过则评估 release 摘要接入，失败则按日志修复，缺 key 则保持 `NOT RUN`。
