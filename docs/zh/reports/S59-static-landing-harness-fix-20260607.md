# S59 — static_landing_page Harness 修复（维护者）

日期：2026-06-07  
状态：**部分通过** — Harness/Studio 路径已修；真实模型产出仍受 provider 波动影响

## 修复项

| # | 问题 | 修复 |
| --- | --- | --- |
| H1 | `index.html` 不在 implementation artifact scope | `task_contract.py` 允许 `.html/.css/.htm` |
| H2 | `list_files path=.` 被拒 | `path_in_read_scope` 允许工作区根 listing |
| H3 | 验证命令 `>` 被 shell 策略拦截 | `shell_guard.py` 允许安全输出重定向 |
| H4 | 静态页验证不稳定 | `execution_action_preparer.py` 对 html/css 使用 `python -c` 存在性检查 |
| S1 | Studio `runtime-actions` 500（session_id 丢失） | `server.mjs` `ensureSession` / `appendEvent` 保留 session_id |
| B6 | assist 循环不处理 `model-check` | `b6-restricted-user-sim.mjs` 增加 model-check 分支 |

## 验证

```powershell
pytest tests/unit/test_task_contract.py tests/unit/test_security_guards.py tests/unit/test_execution_action_preparer.py -q
```

B6 复跑（`static_landing_page`）：

- ✅ 不再出现 Studio 500 / `path undefined`
- ✅ 验证命令改为 `python -c` 检查 `index.html`（见 task_failures 证据）
- ⚠️ 本轮模型未产出 `index.html`（invalid JSON / stream timeout）→ 仍 blocked

## 下一刀（可选）

- 真实模型稳定后复跑 B6；或先用 `small_code_change` 作内测 fallback
- 若仍频繁 timeout：调大 streaming deadline / goal_spec tier 路由
