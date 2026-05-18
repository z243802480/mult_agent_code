# ADR-0002: 候选修改必须先进入隔离工作区

## 状态

Accepted

## 背景

Asteria 的核心价值是把模型生成的代码变成可验证、可回滚、可解释的产物。直接修改主工作区会让失败候选、越权写入、验证失败和多 worker 冲突难以恢复。

## 选项

- 直接写主工作区：实现简单，但失败污染风险高。
- 所有修改先进入 candidate workspace：实现和 promotion 成本更高，但能配合 MergeGate、promotion queue 和 final report 形成可靠闭环。

## 决策

写入型 worker 默认通过 candidate workspace 产出候选变更。promotion 前必须检查 write scope、verification、merge gate、candidate 状态和主工作区状态。失败候选、promotion failure 和 discard 不得污染主工作区。

## 后果

- CandidateWorkspace、MergeGate、CandidatePromotionQueue 是 Runtime OS 核心可靠性边界。
- Git worktree/candidate branch 是优先 backend；无 git 或 tracked dirty 时 fallback 到复制候选目录或停下提示风险。
- 多 worker 协作必须通过独立候选空间和统一 promotion queue 合并。

## 回滚或替代条件

如果某类任务确实只读或只生成可丢弃草稿，可以不创建写入候选；但进入主工作区的写入仍必须经过 promotion 或等价 gate。
