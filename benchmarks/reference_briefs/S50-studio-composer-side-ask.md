# Slice S50 — Composer Quick Ask 子模式

更新时间：2026-06-06  
状态：**已完成**  
依赖：S49 Side Chat（Ctrl+;）

## 1. 对标（S45j）

| Claude Code | Asteria 交付 |
| --- | --- |
| Composer 内 side question | Quick ask 开关 + `/ask` slash |
| 附带 session context | side channel 服务端注入 goal/phase 摘要 |
| 不打断主 turn | 仍走 `channel=side` + `display_level=side` |

## 2. 模块

```text
hooks/useSideChat.ts          composerSideAsk 状态
components/Composer.tsx       子模式 UI + 路由
server.mjs                    sideAskContextHint 富化
styles/composer.css           .composer.sideAskMode
```

## 3. 验收

- [x] Composer 可切换 Quick ask，发送走 side channel
- [x] 发送后自动展开 Side chat 面板
- [x] `/ask` slash 进入子模式
- [x] build + smokes
