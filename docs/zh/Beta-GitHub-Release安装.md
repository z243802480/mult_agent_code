# Beta — GitHub Release 安装（内测者）

更新时间：2026-06-07

**内测者不需要 clone 源码。** 从 [GitHub Releases](https://github.com/z243802480/mult_agent_code/releases) 下载 **`asteria-beta-<版本>.zip`** 即可。

---

## 1. 你需要什么

| 项 | 要求 |
| --- | --- |
| Python | 3.11+（安装脚本会创建独立 venv） |
| Node.js | 18+（仅运行 Studio API；**不需要** npm install） |
| 模型 | strong + medium 各一条 route |
| 磁盘 | ~200MB（含 venv + Studio 预构建 UI） |

---

## 2. 安装（约 5 分钟）

### Windows

```powershell
# 从 Releases 下载 `asteria-beta-<版本>.zip` 后（当前 **0.2.0a2**）：
Expand-Archive .\asteria-beta-0.2.0a2.zip -DestinationPath .\asteria-beta
cd .\asteria-beta
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### macOS / Linux

```bash
unzip asteria-beta-0.2.0a2.zip -d asteria-beta
cd asteria-beta
bash install.sh
```

安装脚本会：

1. 在 `~/.asteria/venv` 创建 Python 虚拟环境并安装 wheel  
2. 将预构建 Studio（含 UI）解压到 `~/.asteria/studio/<版本>`  
3. 写入 `~/.asteria/studio/current` 指针  

**把 venv 的 Scripts（Windows）或 bin（Unix）加入 PATH**，例如：

```powershell
# Windows — 当前会话
$env:Path = "$env:USERPROFILE\.asteria\venv\Scripts;" + $env:Path
asteria version
```

---

## 3. 配置模型

复制包内 `templates/model.routes.validation.example.ps1` 到本机，填入 Key，或在 shell 中设置 `AGENT_MODEL_*` 环境变量。详见 [`Beta用户入门.md`](./Beta用户入门.md) §2.2。

```powershell
asteria model-check --root . --tier strong --json
asteria model-check --root . --tier medium --json
```

两项 `call_ok: true` 后再继续。

---

## 4. 第一个任务

```powershell
mkdir $env:USERPROFILE\asteria-workspace
asteria init --root $env:USERPROFILE\asteria-workspace
asteria studio --root $env:USERPROFILE\asteria-workspace
```

浏览器打开 **http://127.0.0.1:8787**（Release 包 UI 与 API 同端口）。

**推荐 Goal（任务 1 — 做网站）：**

```text
做一个单页静态网站（HTML + CSS），介绍一个产品想法；本地用浏览器能打开预览。
```

逐步清单：[`Beta试跑清单.md`](./Beta试跑清单.md)

---

## 5. Release 资产说明

| 文件 | 用途 |
| --- | --- |
| `asteria-beta-<ver>.zip` | **内测者下载这个**（wheel + Studio + 文档 + 安装脚本） |
| `asteria_runtime-<ver>-py3-none-any.whl` | 高级用户 / 仅 CLI |
| `asteria-studio-<ver>.zip` | 高级用户 / 仅 Studio |
| `SHA256SUMS.txt` | 校验和 |

---

## 6. 维护者发布

```powershell
# 本地构建（需 Node + Python）
python scripts/build_beta_release.py --root .

# 打 tag 触发 GitHub Actions 上传 Release
git tag v0.1.0
git push origin v0.1.0
```

或 Actions → **Release** → **Run workflow**（手动试构建，产物在 workflow artifacts）。

---

## 7. 仍不适合内测者做的事

- clone 仓库、`pip install -e .`
- `gate` / `acceptance` / maintainer 命令
- 生产部署、远程 push

开发者路径见 [`Beta用户入门.md`](./Beta用户入门.md) §2.1（源码 editable 安装）。
