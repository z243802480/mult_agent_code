# Slice S49 — Side Chat（Ctrl+;）

更新时间：2026-06-06  
状态：**已完成**  
依赖：S46 视觉校准、S48 Diff Review

## 1. 对标结论

| Claude Code | Asteria 交付 |
| --- | --- |
| Ctrl+; 打开 side chat | `useSideChat` + `useStudioKeyboard` |
| 主线程不被打断 | `display_level: "side"` 事件不进 Thread |
| 只读问答 | 强制 `mode=chat` + `channel=side` |

## 2. 模块

```text
features/sidechat/SideChatPanel.tsx
features/sidechat/sideChatUtils.ts
hooks/useSideChat.ts
styles/side-chat.css
```

## 3. 验收

- [x] Ctrl+; 切换 side chat 面板
- [x] 消息走 chat 后端，`display_level=side` 不进主 Thread
- [x] 顶栏 Quick ask 按钮
- [x] build + homepage-copy-smoke + side-chat-smoke
