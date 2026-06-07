# Beta 试跑清单（给测试者）

更新时间：2026-06-07

**目标**：在 **30 分钟内** 独立完成第一个任务，**不要** 问维护者「下一步该敲什么命令」。

维护者应给你：**本清单** + [`Beta用户入门.md`](./Beta用户入门.md) + **GitHub Release 安装包**（`asteria-beta-*.zip`）+ 模型 Key 配置说明。  
**不需要** clone 源码。安装步骤：[`Beta-GitHub-Release安装.md`](./Beta-GitHub-Release安装.md)

---

## 开始前

| 项 | 自检 |
| --- | --- |
| Python 3.11+ | ☐ `python --version` |
| Node.js 18+ | ☐ `node --version` |
| 已安装 Release 包 | ☐ `asteria version` 有输出 |
| strong + medium 模型可用 | ☐ 见入门 §2.2 |

---

## 任务（只做任务 1）

**Goal 文案（复制到 Studio Composer → Goal 模式）：**

```text
做一个单页静态网站（HTML + CSS），介绍一个产品想法；本地用浏览器能打开预览。
```

可从空白工作区开始；完成后工作区应有 `index.html`（可选 `styles.css`），浏览器能打开。

**其他任务（可选 · 第二次试跑）**：见 Release 包内 `docs/` 或 [`benchmarks/beta_user_tasks.json`](../../benchmarks/beta_user_tasks.json) — `doc_update`、`small_code_change` 等。

---

## 步骤（按顺序打勾）

### A. 安装（约 10 分钟）

| # | 动作 | 完成 |
| --- | --- | --- |
| A1 | 解压 `asteria-beta-*.zip`，运行 `install.ps1` / `install.sh` | ☐ |
| A2 | PATH 含 venv；`asteria version` 有输出 | ☐ |
| A3 | `model-check` strong + medium 均为 `call_ok: true` | ☐ |
| A4 | `asteria init --root <你的工作区>` | ☐ |
| A5 | `asteria studio --root <工作区>`，浏览器打开 **http://127.0.0.1:8787** | ☐ |

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
| C3 | 工作区里能看到产物（如 `index.html`），浏览器能预览 | ☐ |

### D. Studio 对标 spot-check（可选 · 约 5 分钟）

| # | 动作 | 完成 | 摩擦桶 |
| --- | --- | --- | --- |
| D1 | Inspector **Diff review**：左文件列表 + 右 diff | ☐ | diff |
| D2 | Thread 顶部 **Context** 压力条 → breakdown | ☐ | context |
| D3 | 左侧 **Session** 列表；**Ctrl+Tab** 切换 | ☐ | session |
| D4 | **Ctrl+;** Side chat 或 Composer **Quick ask** | ☐ | side_ask |
| D5 | 长 tool 输出 **Copy** + 展开 | ☐ | diff / thread |

---

## 卡住时（先试这些）

| 现象 | 你先做 |
| --- | --- |
| 模型报错 | `asteria doctor --root <ws> --json` |
| 不知道进度 | Thread Next action / `asteria status --json` |
| 出现 **scope** 决策卡 | **Review contract** → **Continue** |
| Studio 打不开 | 确认 `node --version`；Release 包无需 npm install |

仍无法继续 → 记录卡在哪一步 + 截图，交给维护者填 trial 模板。

---

## 完成后请告诉维护者

1. 总耗时（分钟）
2. A/B/C 哪些步骤未完成
3. 最难的一步（一句话）
4. D1–D5 若有卡点，标注 **diff / context / session / side_ask**
5. 是否愿意再试第二个任务

**不要** push 代码、不要运行 maintainer 专用命令。
