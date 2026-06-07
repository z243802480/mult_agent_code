# Slice S51 — Turn Rewind 入口

更新时间：2026-06-06  
状态：**已完成**  
依赖：S45k 规划、runtime resume/replan 已存在  
计划：[`docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md`](../../docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md)

## 1. 对标（Claude Code `/rewind`）

| CC | Asteria 交付 |
| --- | --- |
| 回到某 turn 之前的状态 | Thread turn 菜单 **Rewind** |
| 不静默改 workspace | 确认对话框 + 说明将触发 resume/replan |
| 主路径可发现 | Verbose 或 turn 展开区可见；Focus 可收进 `…` |

## 2. 行为契约

```text
用户点击 Turn N 的 Rewind
  → 展示确认（将请求 runtime 从该 turn 后续续作/重规划）
  → 调用已有 runtime action（resume 或 replan，按 runDetail 推荐）
  → Thread 不伪造 rewind；证据进 user_progress / Inspector
```

- **不**在 Studio 本地删 events 或 git 回滚  
- **不**新增 runtime 子命令；复用 `api.runtimeAction`  
- 若 run 未 active / 无 run_id：按钮 disabled + tooltip  

## 3. 模块（预期）

```text
features/thread/TurnRewindButton.tsx   （或并入 ConversationTurn）
session/useTurnRewind.ts               （读 runDetail 推荐 action）
styles/thread-turn.css                 （按钮 + 确认条）
studio/scripts/turn-rewind-smoke.mjs
```

## 4. 验收

- [x] 至少一个 turn 展示 Rewind（非最后一轮 · Normal/Verbose）
- [x] 确认后调用 runtime action；events 刷新
- [x] Focus 模式不增加主线程噪音
- [x] `npm run build` + turn-rewind-smoke + homepage-copy-smoke
