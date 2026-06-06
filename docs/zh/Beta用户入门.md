# Beta 用户入门

更新时间：2026-06-06

面向 **早期 Beta 用户**（能配置 API Key、会开终端）。目标：**30 分钟内** 用 Studio 完成第一个编程类任务。

**试跑专用**：维护者发测时请同时给 [`Beta试跑清单.md`](./Beta试跑清单.md)（逐步打勾，无需 gate 词汇）。

## 1. 你需要什么

| 项 | 要求 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 18+（Studio UI） |
| 模型 | strong + medium 各一条 route（见 [`模型供应商规格.md`](./模型供应商规格.md)） |
| 仓库 | 克隆本仓库（Studio 随仓库提供） |

## 2. 十分钟安装

### 2.1 安装 runtime

**开发路径（推荐 Beta）：**

```powershell
cd <repo>
python -m pip install -e .
asteria version
```

**Wheel 路径（验证用）：** 见 [`验证试运行手册.md`](./验证试运行手册.md) §3.1。

### 2.2 配置模型

复制 `templates/model.routes.validation.example.ps1` 到本机私有配置，或设置环境变量：

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "glm"
$env:AGENT_MODEL_STRONG_API_KEY = "<your-key>"
$env:AGENT_MODEL_MEDIUM_PROVIDER = "minimax"
$env:AGENT_MODEL_MEDIUM_API_KEY = "<your-key>"

asteria model-check --root . --tier strong --json
asteria model-check --root . --tier medium --json
```

两项 `call_ok: true` 后再继续。

### 2.3 初始化工作区

```powershell
mkdir my-asteria-workspace
asteria init --root my-asteria-workspace --north-star-title "我的第一个目标"
```

可选：放入 starter 文件 `greet_cli.py`（见 `benchmarks/fixtures/s13_clean_run/greet_cli.py`）。

## 3. 打开 Studio

```powershell
asteria studio --root my-asteria-workspace
```

浏览器打开 **http://127.0.0.1:5174**（UI）· API **http://127.0.0.1:8787**。

首次会自动 `npm install`（仅 Studio 目录，一次性）。

## 4. 完成第一个任务（推荐）

Beta 任务包：[`benchmarks/beta_user_tasks.json`](../../benchmarks/beta_user_tasks.json)

**任务 1 — small_code_change：**

在 Composer 选择 **Run / Goal** 模式，输入：

```text
给一个小 CLI 增加 --version 参数，并补一个测试。
```

你会看到：

1. Thread 里 plan / tool / verification 进度（不是 raw JSON）
2. 写文件或跑命令前 **权限卡**（Allow / Deny）
3. 完成后 Thread 顶部 **Next action** 出现 **审查结果** / **接受结果**

### 4.1 审查与接受

| 步骤 | Studio | CLI（等价） |
| --- | --- | --- |
| 审查 | 点「审查结果」或 Composer `/review` | `asteria review --root <工作区>` |
| 接受 | 点「接受结果」或 `/accept` | `asteria accept --root <工作区>` |

> **说明**：`goal` 跑完通常已内嵌 review；若 `asteria status` 显示 `ready_for_accept`，可直接 `accept`，无需再 `review`。CLI **没有** `--latest` 参数，默认对当前 session 的最新 run 操作。

接受后产物写入工作区；North Star milestone 会自动链接 run（若已配置）。

## 5. 续作第二个 goal

同一会话 Composer 再发一条 goal，或：

```powershell
asteria goal "续作：补充文档说明用法" --root my-asteria-workspace
```

## 6. 出问题时

| 现象 | 动作 |
| --- | --- |
| 模型不通 | `asteria doctor --root <ws> --json` |
| 任务卡住 | Thread「Next action」或 `asteria status --json` |
| 出现 **范围确认 / scope** | 选 **Review contract**，再点 **Continue** |
| 需要证据 | Inspector（右侧），**不要**看 gate 主屏 |
| 导出诊断 | `asteria evidence-bundle --root <ws> --json`（给维护者） |

## 7. Beta 边界（请知悉）

- **监督式自主**：写文件/跑命令会要权限；accept 前需 review。
- **不做**：生产部署、远程 push、蜂群并行（尚未开放）。
- **适合**：小 CLI、文档更新、单文件 bugfix（见 beta 任务包）。

## 8. 验证你装对了

维护者 green_checks（可选自测）：

```powershell
pytest tests/integration/test_phase7_beta_user_path_gate.py -q
node studio/scripts/beta-workflow-smoke.mjs
node studio/scripts/b6-restricted-user-sim.mjs
python scripts/s15_wheel_install_smoke.py --root .
```
