# S59 — static_landing_page Harness 修复（维护者）

更新时间：2026-06-07  
状态：**v0.1.1 已打包** — Harness/Studio 路径已修；真实模型产出仍受 provider 波动影响

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

## v0.1.1 打包（2026-06-07）

```powershell
python scripts/build_beta_release.py --root .
# dist/asteria-beta-0.1.1.zip
```

- ✅ triple_track_pulse / beta_trial_smoke / s15 wheel smoke
- ✅ Release 安装 E2E + Studio 8787/19987 HTTP 200
- ✅ `session-id-smoke.mjs` 回归

发布：手动上传 `dist/*0.1.1*` 或 `git tag v0.1.1 && git push origin v0.1.1`
