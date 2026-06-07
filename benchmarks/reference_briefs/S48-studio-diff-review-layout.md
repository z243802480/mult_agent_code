# Slice S48 — Diff Review 左文件右内容

更新时间：2026-06-06  
状态：**已完成**  
依赖：S46 视觉校准、S47 Session 侧栏

## 1. 对标结论（S46 遗留）

| Claude Code | 交付 |
| --- | --- |
| Diff pane：左侧文件树、右侧 diff 内容 | `DiffReviewPane` 双栏布局 |
| 单一审改动任务 | 文件列表与 preview 同屏，不再纵向堆叠 |
| Ctrl+Shift+D Diff Focus | 已有，双栏在加宽 panel 下更易读 |

defer：Side chat（Ctrl+;）→ S49 RFC

## 2. 模块

```text
features/inspector/diff/DiffScopeToolbar.tsx
features/inspector/diff/DiffFileList.tsx
features/inspector/DiffReviewPane.tsx
styles/inspector-diff-review.css
```

## 3. 验收

- [x] 右栏 Primary 为左文件列表 + 右 diff/preview
- [x] 无选中文件时右侧显示占位提示
- [x] DiffScopePanel 仍导出（smoke 兼容）或 smoke 更新
- [x] build + homepage-copy-smoke + turn-diff-scope-smoke
