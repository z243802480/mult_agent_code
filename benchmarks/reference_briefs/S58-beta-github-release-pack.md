# Slice S58 — Beta GitHub Release 分发包

更新时间：2026-06-07  
状态：**🔄 active**  
依赖：S56 · S57

## 目标

内测者 **不 clone 源码**；从 GitHub Releases 下载 `asteria-beta-*.zip` 即可安装并打开 Studio。

| # | 交付 | 成功标准 |
| --- | --- | --- |
| R1 | `build_beta_release.py` | wheel + studio zip + beta pack + SHA256 |
| R2 | `beta_install.ps1` / `.sh` | venv + wheel + Studio 到 `~/.asteria/studio` |
| R3 | `.github/workflows/release.yml` | tag `v*` 上传 Release assets |
| R4 | 内测文档 + 任务 | Release 安装路径；任务 1 = 静态站 |

## green_checks

```powershell
python scripts/beta_task_pack_check.py --root .
python scripts/build_beta_release.py --root .
pytest tests/unit/test_studio_command.py tests/unit/test_build_beta_release.py -q
```

## 验收

- [ ] Release 包可安装且 `asteria studio` 打开 8787 UI
- [ ] 内测文档不再默认 `pip install -e .`
- [ ] GitHub Actions release workflow 就位
