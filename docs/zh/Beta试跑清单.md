# Beta 试跑清单（给测试者）

更新时间：2026-06-06

**目标**：在 **30 分钟内** 独立完成第一个任务，**不要** 问维护者「下一步该敲什么命令」。

维护者只应给你：**本清单** + [`Beta用户入门.md`](./Beta用户入门.md) + 仓库 clone 地址 + 模型 Key 配置方式。

---

## 开始前

| 项 | 自检 |
| --- | --- |
| Python 3.11+ | ☐ `python --version` |
| Node.js 18+ | ☐ `node --version` |
| 已 clone 仓库 | ☐ 有 `studio/` 目录 |
| strong + medium 模型可用 | ☐ 见入门 §2.2 |

---

## 任务（只做任务 1）

**Goal 文案（复制到 Studio Composer → Goal 模式）：**

```text
给一个小 CLI 增加 --version 参数，并补一个测试。
```

可选：在工作区放 starter 文件 `greet_cli.py`（维护者可提供 `benchmarks/fixtures/s13_clean_run/greet_cli.py` 副本）。

---

## 步骤（按顺序打勾）

### A. 安装（约 10 分钟）

| # | 动作 | 完成 |
| --- | --- | --- |
| A1 | `pip install -e .`（在仓库根目录） | ☐ |
| A2 | `asteria version` 有输出 | ☐ |
| A3 | `model-check` strong + medium 均为 `call_ok: true` | ☐ |
| A4 | `asteria init --root <你的工作区>` | ☐ |
| A5 | `asteria studio --root <你的工作区>`，浏览器打开 UI | ☐ |

### B. 执行任务（约 15 分钟）

| # | 动作 | 完成 |
| --- | --- | --- |
| B1 | Studio 里发 Goal（见上文文案） | ☐ |
| B2 | Thread 能看到 plan / tool / verification 类进度（不是满屏 JSON） | ☐ |
| B3 | 写文件或跑命令前出现 **权限卡**，你点了 Allow 或 Deny | ☐ |
| B4 | 任务跑到「可审查」状态（Thread 出现 **审查结果** 或类似提示） | ☐ |

### C. 审查与接受（约 5 分钟）

| # | 动作 | 完成 |
| --- | --- | --- |
| C1 | 点 **审查结果**（或 Composer `/review`；若 goal 已 review 可跳过） | ☐ |
| C2 | 点 **接受结果**（或 `asteria accept --root <工作区>`） | ☐ |
| C3 | 工作区里能看到产物（如改过的 `.py` 或测试文件） | ☐ |

---

## 卡住时（先试这些）

| 现象 | 你先做 |
| --- | --- |
| 模型报错 | `asteria doctor --root <ws> --json` |
| 不知道进度 | Thread 顶部 Next action / `asteria status --json` |
| 需要细节 | 右侧 Inspector（**不要**找 gate 主屏） |

仍无法继续 → 记录 **卡在哪一步 + 截图/报错原文**，交给维护者填 [`S14-beta-user-trial-template.md`](./reports/S14-beta-user-trial-template.md)。

---

## 完成后请告诉维护者

1. 总耗时（分钟）
2. A/B/C 哪些步骤未完成
3. 最难的一步是什么（一句话）
4. 是否愿意再试第二个 beta 任务（doc_update）

**不要** push 代码、不要改仓库配置、不要运行 maintainer 专用命令（gate、acceptance 等）。
