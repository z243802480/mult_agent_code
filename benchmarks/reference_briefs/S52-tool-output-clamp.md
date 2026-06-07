# Slice S52 — Tool 输出 ClampedOutput

更新时间：2026-06-06  
状态：**已完成**  
依赖：S45i、S46 LiveStream 降噪  
计划：[`docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md`](../../docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md)

## 1. 对标（Claude Code CLI tool 结果）

| CC | Asteria 交付 |
| --- | --- |
| stdout 默认限高可扫读 | `ClampedOutput` max-height + fade |
| 一键 copy | copy 按钮（clipboard API） |
| 需要时看全量 | Verbose 或 expand 展开 |

## 2. 范围

- 统一 **LiveStream**、**TurnMiddle** tool 块输出渲染  
- 复用或提取现有 `ClampedOutput`（若 S46 已有则收敛一处）  
- 禁词：smoke 扫描路径避免 `command` 用户可见文案（用 action/output 等）  

## 3. 验收

- [x] tool 输出默认 clamp（建议 max-height ~160px）
- [x] copy 可用；展开后显示全量
- [x] Focus 模式保持降噪（不默认全展开）
- [x] build + thread 相关 smoke
