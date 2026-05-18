# ADR-0001: 1.0 前优先使用 JSON/JSONL 状态存储

## 状态

Accepted

## 背景

Asteria 当前仍处于 0.x Runtime OS alpha 阶段，需要快速演进 schema、验收证据和控制面。项目目标要求本地优先、可审计、可恢复，并且 MVP 假设明确写着先使用 filesystem + JSON/JSONL，再评估 SQLite。

## 选项

- 继续使用 JSON/JSONL：便于人工检查、diff、打包灰度、诊断导出和 schema 演进；代价是查询和迁移能力有限。
- 现在迁移 SQLite：查询能力更强；代价是迁移复杂度、损坏恢复、人工审计和安装包边界都会变重。

## 决策

1.0 前继续以 `.asteria/` 下的 JSON/JSONL 作为主状态存储。新增持久化对象必须有 schema、loader 或 migration 策略，并在控制面中可诊断。

## 后果

- 控制面和报告优先读取结构化文件，而不是引入数据库依赖。
- 长期需要 migration registry，避免 loader 补默认值无限散落。
- 当跨 run 查询、并发写入、压缩归档或团队同步成为瓶颈时，重新评估 SQLite。

## 回滚或替代条件

如果 JSONL 写入冲突、跨 run 查询成本或诊断包体积成为 alpha 阻塞，应起草 SQLite 迁移 RFC。
