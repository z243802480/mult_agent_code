# Beta 用户入门

更新时间：2026-06-07

面向 **早期 Beta 用户**（能配置 API Key、会开终端）。目标：**30 分钟内** 用 Studio 完成第一个任务（推荐：做一个静态网页）。

**试跑专用**：[`Beta试跑清单.md`](./Beta试跑清单.md)（逐步打勾）。

## 1. 你需要什么

| 项 | 要求 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 18+（运行 Studio；Release 包**不需要** npm install） |
| 模型 | strong + medium 各一条 route |
| 安装包 | GitHub Release **`asteria-beta-*.zip`**（见 [`Beta-GitHub-Release安装.md`](./Beta-GitHub-Release安装.md)） |

> **内测者**：不要 clone 源码。维护者发 Release 包即可。

## 2. 安装

### 2.1 Release 包（内测推荐）

见 [`Beta-GitHub-Release安装.md`](./Beta-GitHub-Release安装.md)：

1. 下载 `asteria-beta-<版本>.zip`
2. 运行 `install.ps1` / `install.sh`
3. 将 `~/.asteria/venv/Scripts`（或 `bin`）加入 PATH

### 2.2 源码路径（仅开发者）

```powershell
cd <repo>
python -m pip install -e .
cd studio && npm install && cd ..
```

### 2.3 配置模型

复制 Release 包内 `templates/model.routes.validation.example.ps1`，或设置环境变量：

```powershell
asteria model-check --root . --tier strong --json
asteria model-check --root . --tier medium --json
```

两项 `call_ok: true` 后再继续。详见 [`模型供应商规格.md`](./模型供应商规格.md) §6。

### 2.4 初始化工作区

```powershell
mkdir $env:USERPROFILE\asteria-workspace
asteria init --root $env:USERPROFILE\asteria-workspace --north-star-title "我的第一个目标"
```

## 3. 打开 Studio

```powershell
asteria studio --root $env:USERPROFILE\asteria-workspace
```

- **Release 包**：浏览器打开 **http://127.0.0.1:8787**（UI + API 同端口）
- **源码开发**：UI **http://127.0.0.1:5174** · API **8787**

## 4. 完成第一个任务

任务包：Release 包内 `docs/` 或 [`benchmarks/beta_user_tasks.json`](../../benchmarks/beta_user_tasks.json)

**任务 1 — 静态网站（推荐）：**

```text
做一个单页静态网站（HTML + CSS），介绍一个产品想法；本地用浏览器能打开预览。
```

你会看到：

1. Thread 里 plan / tool / verification 进度
2. 写文件前 **权限卡**（Allow / Deny）
3. 完成后 **审查结果** / **接受结果**

### 4.1 审查与接受

| 步骤 | Studio | CLI |
| --- | --- | --- |
| 审查 | 「审查结果」或 `/review` | `asteria review --root <工作区>` |
| 接受 | 「接受结果」或 `/accept` | `asteria accept --root <工作区>` |

## 5. 第二个任务（可选）

- **改文档**：`doc_update`
- **小 CLI**：`small_code_change`（维护者/engineering 向）

## 6. 出问题时

| 现象 | 动作 |
| --- | --- |
| 模型不通 | `asteria doctor --root <ws> --json` |
| 任务卡住 | Thread Next action / `asteria status --json` |
| scope 决策卡 | **Review contract** → **Continue** |

## 7. Beta 边界

- **监督式自主**：写文件/跑命令需权限；accept 前需 review
- **不做**：生产部署、远程 push、蜂群并行
- **适合**：静态页、文档、小脚本 — 见 beta 任务包
