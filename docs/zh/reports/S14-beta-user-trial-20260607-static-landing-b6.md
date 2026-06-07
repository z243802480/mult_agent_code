# S14 Beta 用户试跑 — static_landing_page B6（维护者）

日期：2026-06-07  
测试者：`maintainer-b6`（**维护者** · 非正式 B6 签字）  
工作区：`%TEMP%\b6-static-landing-1780814814`  
run_id：`run-20260607-0001`

## 1. 试跑信息

| 字段 | 填写 |
| --- | --- |
| 日期 | 2026-06-07 |
| 测试者代号 | maintainer-b6 |
| 是否维护者 | **是** |
| 环境 OS | Windows 10 |
| Python / Node | 3.13.13 / v24.13.0 |
| 安装路径 | clone + `pip install -e .`（B6 sim 开发路径） |
| 模型 tier | strong: glm-5 · medium: MiniMax-M2.7 |
| 脚本 | `B6_TASK_ID=static_landing_page node studio/scripts/b6-restricted-user-sim.mjs` |

## 2. 步骤结果

| 步骤 | 通过 | 耗时(min) | 备注 |
| --- | --- | --- | --- |
| A1–A5 安装 + Studio | ✅ | ~0.3 | init · model-check · studio preview |
| B1–B4 Goal 执行 | ❌ | ~2.6 | 5× debug 后 sim 中止（`too many debug cycles`） |
| C1–C3 Review + Accept | ❌ | — | 未到达 ready_for_accept |

**合计**：约 **3 分钟**（失败于 execute/repair 循环）

## 3. 任务结果

| 项 | 填写 |
| --- | --- |
| Beta 任务 ID | `static_landing_page` |
| Goal 独立完成 | ❌ |
| Review | ❌ |
| Accept | ❌ |
| 产物可见（工作区根） | ❌（`index.html` 仅在 candidate workspace） |
| friction | decide=0 · debug=5 · resume=0 |

## 4. 阻塞与反馈

- **repair/debug 死循环**：B6 sim 在 `blocked|debug` 状态连续触发 5 次 debug 后退出。
- **Shell 策略拦截验证**：`run_command denied by policy: Shell control operator denied: >` — 模型用重定向做验证时被拒。
- **candidate 未 promotion**：`index.html` / `styles.css` 出现在 `.asteria/runs/.../cw/.../`，工作区根目录无文件，contract 报 `expected changed files were not modified`。
- **首次 execute**：`tool_permission_denied` — read path `.` 被拒（task-0001）。

### 4.1 Studio friction 分桶

| 桶 | 分数 (0–3) | 一句话 |
| --- | --- | --- |
| diff | 0 | 未进入 review/diff 阶段 |
| context | 0 | — |
| session | 1 | permission_request → Allow 正常 |
| side_ask | 0 | — |

Studio friction (diff/context/session/side_ask): 0 / 0 / 1 / 0

## 5. 维护者过门

| 检查 | 状态 | 证据 |
| --- | --- | --- |
| 非维护者独立完成 | ❌ | 维护者 sim |
| run-health 未爆炸 | ✅ | 单次 run，cost 未 hard-stop |
| real provider 任务可完成 | ❌ | static_landing_page 未过 |
| Release 安装路径 | ✅（同日另测） | `install.ps1` + studio 8787 OK |

## 6. 结论

| 项 | 选择 |
| --- | --- |
| B6 试跑 | ❌ **未通过** — Harness P0：静态站任务 verification/promotion |
| 下一 slice 建议 | **轨道 H**：静态页/file_artifact 验证命令策略 + candidate promotion 到工作区根 |
| 签字人 | maintainer-b6（Auto） |
| 签字日期 | 2026-06-07 |

## 7. 复现

```powershell
cd h:\mult_agent_code
$env:B6_TASK_ID = "static_landing_page"
$env:B6_SIM_WORKSPACE = "$env:TEMP\b6-static-landing-test"
node studio/scripts/b6-restricted-user-sim.mjs
```

证据：`task_failures.jsonl`（repair_contract_violation · shell `>` denied · changed_files 在 cw 未 promotion）。
