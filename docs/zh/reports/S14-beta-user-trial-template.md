# S14 Beta 用户试跑 — 维护者记录模板

复制本文件为 `S14-beta-user-trial-<YYYYMMDD>-<代号>.md`，试跑结束后归档到 [`docs/zh/reports/`](./)。

---

## 1. 试跑信息

| 字段 | 填写 |
| --- | --- |
| 日期 | |
| 测试者代号 | （可匿名，如 `beta-01`） |
| 是否维护者 | **必须：否** |
| 环境 OS | |
| Python / Node 版本 | |
| 安装路径 | clone + `pip install -e` / wheel（圈选） |
| 模型 tier | strong / medium provider 名称 |

---

## 2. 给测试者的材料（维护者自检）

| 项 | 已提供 |
| --- | --- |
| [`Beta试跑清单.md`](../Beta试跑清单.md) | ☐ |
| [`Beta用户入门.md`](../Beta用户入门.md) | ☐ |
| 仓库 clone 地址 | ☐ |
| API Key 配置说明（无私钥进 git） | ☐ |
| **未**口头逐步带操作 | ☐ |

---

## 3. 步骤结果（对照试跑清单 A/B/C）

| 步骤 | 通过 | 耗时(min) | 备注 |
| --- | --- | --- | --- |
| A1–A5 安装 + Studio | ☐ | | |
| B1–B4 Goal 执行 | ☐ | | |
| C1–C3 Review + Accept | ☐ | | |
| **合计** | | | 目标 ≤30 min |

---

## 4. 任务结果

| 项 | 填写 |
| --- | --- |
| Beta 任务 ID | `small_code_change` |
| Goal 是否独立完成 | ☐ 是 ☐ 否 |
| Review 是否完成 | ☐ 是 ☐ 否 |
| Accept 是否完成 | ☐ 是 ☐ 否 |
| 产物可见（文件/diff） | ☐ 是 ☐ 否 |
| studio-benchmark / 主观评分 (0–1) | |

---

## 5. 阻塞与反馈（测试者原话摘要）

```text
（最难的一步、报错、UX 问题）
```

### 5.1 Studio friction 分桶（F2 · 可选）

按 [`Beta试跑清单.md`](../Beta试跑清单.md) D1–D5，填写 **0–3**（0=无摩擦，3=严重阻塞）：

| 桶 | 分数 (0–3) | 一句话 |
| --- | --- | --- |
| diff | | |
| context | | |
| session | | |
| side_ask | | |

汇总行（维护者脚本读取）：`Studio friction (diff/context/session/side_ask): 0 / 0 / 0 / 0`

---

## 6. 维护者过门（B6 签字前）

| 检查 | 状态 | 证据 |
| --- | --- | --- |
| 非维护者独立完成 | ☐ | 本节 §3–§5 |
| run-health 未爆炸 | ☐ | `user_progress` 体积 / replan 次数 |
| real provider 任务可完成 | ☐ | run id / benchmark score |
| wheel 路径（可选本轮） | ☐ / defer | [`验证试运行手册`](../验证试运行手册.md) §3.1 |

---

## 7. 结论

| 项 | 选择 |
| --- | --- |
| B6 试跑 | ☐ **通过** — 更新 [`S14-beta-user-path-signoff-20260606.md`](./S14-beta-user-path-signoff-20260606.md) B6=✅ |
| | ☐ **未通过** — 开 S15 onboarding 修复项，**不**扩 Phase 5 |
| 签字人 | |
| 签字日期 | |

---

## 8. 附件（可选）

- `evidence-bundle` 路径（脱敏）
- 截图目录
- run_id / session_id
