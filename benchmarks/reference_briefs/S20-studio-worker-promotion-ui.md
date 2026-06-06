# Slice S20 — Studio Worker Progress + Promotion UI

## observed_pattern

- 主 Thread 应显示 **Background work 进度条**（done/total），不用 gate 词汇。
- Inspector 展示 candidate export、merge preview、pending promotion 证据。
- Beta 用户主屏只说「需要 review / 已完成」，细节在 Inspector。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| `runtime_progress.worker_summary` | progress_percent、workers、promotion_hint | ✅ |
| `promotion_preview` API 字段 | export + dry-run + pending 汇总 | ✅ |
| Thread `WorkerProgressBar` | EventCard 内嵌进度条 | ✅ |
| Inspector `PromotionPreviewPanel` | Candidate merge preview | ✅ |
| smoke | `s20-worker-promotion-smoke.mjs` | ✅ |

## focus

1. 主屏：Background work + 进度条 + promotion_hint（无 merge gate 字样）
2. Inspector：Candidate merge preview 面板
3. server.mjs 读取 S19 jsonl 证据

## green_checks

```bash
node studio/scripts/s20-worker-promotion-smoke.mjs
node studio/scripts/run-detail-smoke.mjs
python scripts/steady_iteration_check.py --root . --skip-b6
```

## 退出条件

- smoke 绿
- promotion_preview + worker_summary 字段契约稳定
- S21：1 disjoint-write 灰度（maintainer）
