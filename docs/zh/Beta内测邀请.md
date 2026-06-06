# Beta 内测邀请（维护者用）

更新时间：2026-06-06

面向 **3–5 名** 早期测试者。维护者复制下方消息发送，并附上私有材料链接（不要公开 API Key）。

## 1. 邀请消息模板

```text
你好，

邀请你试用 Asteria Beta（本地编程 agent + Studio UI）。

你需要：
- Windows / macOS / Linux，Python 3.11+，Node.js 18+
- 自备 strong + medium 模型 API Key（配置说明见附件）
- 约 30 分钟完成第一个小任务

请按附件《Beta试跑清单》逐步操作，不要等我口头带命令。
完成后把清单底部 4 项反馈发给我即可。

材料：
- Beta用户入门.md
- Beta试跑清单.md
- 仓库 clone：<你的私有/公开地址>

谢谢！
```

## 2. 维护者发放清单

| # | 材料 | 路径 |
| --- | --- | --- |
| 1 | 入门 | [`Beta用户入门.md`](./Beta用户入门.md) |
| 2 | 试跑清单 | [`Beta试跑清单.md`](./Beta试跑清单.md) |
| 3 | 记录模板 | [`reports/S14-beta-user-trial-template.md`](./reports/S14-beta-user-trial-template.md) |
| 4 | Starter 文件 | `benchmarks/fixtures/s13_clean_run/greet_cli.py` |
| 5 | 模型模板 | `templates/model.routes.validation.example.ps1` |

## 3. 内测范围

| 允许 | 暂不开放 |
| --- | --- |
| 任务 1 `small_code_change` | 生产部署 |
| 可选任务 2 `doc_update` | 远程 push |
| `pip install -e .` 或 wheel 安装 | gate / acceptance 维护命令 |
| Studio Goal → Review → Accept | 蜂群并行 |

## 4. 常见卡点（提前告知）

| 现象 | 测试者动作 |
| --- | --- |
| 出现 **权限卡** | 点 Allow（写文件/跑命令前） |
| 出现 **范围确认**（scope） | 选「Review contract」允许补测试文件，再点 Continue |
| 模型不通 | `asteria doctor --root <ws> --json` |
| 超过 30 分钟 | 记录卡在哪一步 + 截图，不必硬撑 |

## 5. 反馈汇总

试跑结束后维护者填写 [`S14-beta-user-trial-template.md`](./reports/S14-beta-user-trial-template.md)，归档到 `docs/zh/reports/`。

维护者汇总多条试跑反馈：

```powershell
python scripts/beta_friction_aggregate.py --root . --markdown
python scripts/beta_friction_aggregate.py --root . --write-md docs/zh/reports/beta-friction-aggregate-latest.md
```

**过门**：至少 1 名非维护者独立完成 A/B/C，或维护者确认 Agent 受限模拟已签字（Phase 7 已关闭）。

## 6. 相关签字

- Phase 7 关闭：[`phase7-beta-close-signoff-20260606.md`](./reports/phase7-beta-close-signoff-20260606.md)
- S15 硬化：[`S15-beta-hardening-signoff-20260606.md`](./reports/S15-beta-hardening-signoff-20260606.md)
