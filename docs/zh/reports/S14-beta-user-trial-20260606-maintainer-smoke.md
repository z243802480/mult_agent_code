# S14 Beta 用户试跑 — 维护者 smoke（非 B6 签字）

日期：2026-06-06  
测试者：`maintainer-smoke`（**非 B6 合格试跑**）  
工作区：`H:\test_agent`

## 1. 试跑信息

| 字段 | 填写 |
| --- | --- |
| 日期 | 2026-06-06 |
| 测试者代号 | maintainer-smoke |
| 是否维护者 | **是**（故不能作为 B6 签字） |
| 环境 OS | Windows 10 |
| Python / Node | 3.13.13 / v24.13.0 |
| 安装路径 | clone `mult_agent_code` + `pip install -e .` |
| 模型 tier | strong: glm-5.1 · medium: MiniMax-M2.7 |

## 2. 步骤结果

| 步骤 | 通过 | 耗时(min) | 备注 |
| --- | --- | --- | --- |
| A1–A5 安装 + Studio 预览 | ✅ | ~2 | `doctor` pass；`studio --json` OK |
| B1–B4 Goal 执行 | ✅ | ~3 | run `run-20260606-0001`；3× repair 后收敛 |
| C1–C3 Review + Accept | ✅ | ~1 | goal 内嵌 review；`asteria accept --root H:\test_agent` |

**合计**：约 **6 分钟**（CLI 路径；未走 Studio UI 点击）

## 3. 任务结果

| 项 | 填写 |
| --- | --- |
| Beta 任务 ID | `small_code_change` |
| Goal 独立完成 | ✅（维护者执行） |
| Review | ✅ score 0.90 |
| Accept | ✅ `workflow_state: accepted` |
| 产物 | `greet_cli.py --version` → `greet_cli 1.0.0`；`pytest` 3 passed |
| run-health | ✅ pass（user_progress ~1.5MB，724 events） |

## 4. 阻塞与反馈

- **repair 偏多**：同一 goal 内 3 轮 debug/repair 才产出 `greet_cli.py` / `test_greet_cli.py`；最终验证 55/55 通过。
- **文档偏差（已修）**：Beta 入门曾写 `accept --latest`，CLI 实际为 `asteria accept --root <ws>`。
- **Studio**：API `8790` 上 `diagnostics.workflow` 在 accept 后正确为 `accepted`。

## 5. 结论

| 项 | 选择 |
| --- | --- |
| B6 试跑 | ☐ 通过 — **不适用**（维护者 smoke） |
| | ✅ **工程路径验证通过** — 可作为 B6 发测前参考 |
| 下一步 | 找 **1 名非维护者** 按 [`Beta试跑清单.md`](../Beta试跑清单.md) 复跑 |

## 6. 复现命令

```powershell
pip install -e h:\mult_agent_code
copy benchmarks\fixtures\s13_clean_run\greet_cli.py h:\test_agent\
asteria init --root h:\test_agent --north-star-title "Beta trial"
asteria goal "给 greet_cli.py 增加 --version 参数，并补一个测试。" --root h:\test_agent --no-research
asteria accept --root h:\test_agent
python h:\test_agent\greet_cli.py --version
pytest h:\test_agent\test_greet_cli.py -q
```
