# Slice S47 — Session 侧栏过滤与分组

更新时间：2026-06-06  
状态：**已完成 · Wave 3–5**  
依赖：S46 视觉校准（Focus Layout + 模块化）

## 1. 对标结论

| Claude Code | Asteria 差距（S46 前） | S47 交付 |
| --- | --- | --- |
| Session 列表可扫读、按时间分组 | 扁平列表，多任务时难定位 | **Today / Yesterday / Earlier** 分组 |
| 快速缩小范围 | 无 filter | **All / Recent** 过滤（localStorage） |
| 侧栏 icon 模式保留 live 点 | ✅ | 分组逻辑复用于 rail |

## 2. 设计原则

```text
默认 All + 日期分组；Recent = 7 天内 updated_at。
Focus 侧栏：隐藏 Workspace health，保留紧凑 filter + 分组。
过滤状态 localStorage：asteria.studio.sessionFilter
```

## 3. 功能模块

```text
studio/src/features/sidebar/sessionListUtils.ts
studio/src/features/sidebar/SessionList.tsx
studio/src/features/sidebar/SessionRail.tsx
studio/src/hooks/useSessionListFilter.ts
```

## 4. 样式分片（Wave 4–5 · 降复杂度）

`styles.css` 仅保留 `@import` 入口：

| 文件 | 职责 |
| --- | --- |
| `tokens.css` | design tokens + reset |
| `shell.css` | appShell · pane splitter |
| `sidebar.css` | 侧栏 chrome · session row |
| `layout.css` | missionPane · topBar · banner |
| `components.css` | permission · signal · decision · worker |
| `thread-shell.css` | thread 容器 · runtime · empty · narrative 步骤壳 |
| `thread-turn.css` | Turn 布局 · LiveStream · file chips · TurnFinal |
| `thread-narrative.css` | NarrativeStep 遗留 · report · event 文本 |
| `composer.css` | 输入区 |
| `inspector-panel.css` | 右栏壳 · Advanced · Debug Agent |
| `inspector-evidence.css` | Evidence Explorer · tabs · routes |
| `inspector-diff.css` | git · diff preview · context panel |
| `session-list.css` | filter / group（S47） |

## 5. 验收

- [x] All / Recent 切换且记忆
- [x] 展开侧栏 session 按 Today/Yesterday/Earlier 分组
- [x] styles 按域分片，`styles.css` 无业务规则
- [x] build + homepage-copy-smoke + s45-parity-smoke
