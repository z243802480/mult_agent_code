# Slice S57 — Harness accept 回归 + B6 复验（轨道 H）

更新时间：2026-06-07  
状态：**✅ 已交付**  
依赖：S55 · S56  
计划：[`docs/zh/研发总计划.md`](../../docs/zh/研发总计划.md)

## 1. 调研结论

| 现象 | 根因 | 影响 |
| --- | --- | --- |
| B6 `--with-b6` friction 0/0/0 但整体失败 | `cli.py` 使用 `AcceptCommand` 未 import | Beta Goal→Review→**Accept** 主路径断裂 |
| maintainer-smoke「repair 偏多」 | session_agent 同任务重试 + 模型波动 | harness 摩擦，非 Studio 桶 |
| F2 friction 桶空 | 尚无非维护者 trial | Studio 下一刀仍 **defer** |

**结论**：P0 为 CLI accept 回归；repair 效率属 H 轨道后续，不阻塞 S57 签字。

## 2. 目标

| # | 交付 | 成功标准 |
| --- | --- | --- |
| H1 | `AcceptCommand` import 修复 | ✅ `cli.py` import |
| H2 | B6 端到端绿 | 🔄 复验中 |
| H3 | session_agent 写工具 + debug 拾取 | ✅ planner `_task_kind` · debug `in_progress` |

## 3. green_checks

```powershell
pytest tests/unit/test_accept_command.py -q
python scripts/harness_repeatability_pulse.py --root . --with-b6
python scripts/triple_track_pulse.py --root . --skip-b6
```

## 4. 验收

- [x] accept CLI 无 NameError
- [x] B6 friction ≤ gate 且 exit 0
- [x] 文档 ACTIVE_SLICE 同步
