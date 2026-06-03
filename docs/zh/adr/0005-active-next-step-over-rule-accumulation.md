# ADR-0005: Active Next Step 优先于规则累积

## 状态

Accepted

## 背景

Asteria 的目标不是把模型输出约束到越来越窄，而是让模型在清晰能力边界内持续推进任务。随着 route、deadline、context、capability、worker、promotion、review 等 gate 增多，系统很容易进入一种危险状态：每次遇到宽泛输出或历史失败，就新增一个代码分支或限制条件；长期看会形成难以维护的面条逻辑，并让 agent 频繁停在无风险环节。

Claude Code 等成熟编程 agent 产品的启发是：工具、任务、验证和恢复要形成简洁循环。Runtime 应保护不可逆风险，并把失败转成下一步可恢复动作；不应把历史噪声或内部诊断直接变成前台阻断。

## 决策

产品和 Runtime 控制面采用 **Active Next Step** 原则：

1. 用户和模型默认只看到当前可执行的下一步，而不是所有历史失败、内部诊断和旧 gate 原因。
2. 历史失败必须被分类为 active、superseded、historical 或 maintainer-only；只有 active 项可以驱动默认 `recommended_actions`。
3. 新增 gate 前必须说明它保护的风险边界、恢复动作和降级路径；不能只因为模型输出宽泛就新增阻断规则。
4. 宽泛或不完整的模型输出优先进入 `repair | replan | ask | stop` 决策链，而不是让 Runtime 追加越来越多特殊分支。
5. 当新鲜 evidence 已证明问题被纠正，控制面必须更新下一步动作，不能继续展示旧的暂停、阻断或扩容禁止建议。
6. 默认产品面只展示 active next step；Inspector、evidence bundle 和 maintainer 命令才展示 raw evidence、historical review 和 superseded noise。

## 实现约束

- `status`、`gate-status`、`capability-report`、Studio 主屏和 final report 必须优先消费 active next step。
- `recommended_actions` 必须从 active blocking/review 生成；不得直接复用未分类的历史 actions。
- `superseded_review`、`historical_review`、`release_evidence_override` 等字段可以保留给 Inspector，但不应驱动默认用户动作。
- 对真实风险使用强 gate：写入主工作区、promotion、merge、rollback、远程 push、预算 hard-stop、真实 provider 放量和发布验收。
- 对探索、readonly、fake-path planner、局部 debug/replan 使用 light trace 或 review，除非出现明确不可逆风险。

## 反查要求

新增或修改 gate/status/report 逻辑时，必须反查是否存在以下模式：

- 旧失败被新鲜 evidence 覆盖后仍驱动 `recommended_actions`。
- review 状态被误用成 blocked。
- 用户默认界面展示 maintainer-only 原因。
- 同一个风险在多个控制面生成互相矛盾的下一步。
- 为处理某类模型宽泛回答新增多个特殊分支，而不是让它进入统一 loop decision。

## 后果

这会减少过度收紧带来的停滞，让 Runtime 的复杂度集中在少量稳定抽象上：能力边界、风险 gate、证据分类、loop decision 和 active next step。代价是部分历史诊断不会在默认产品面直接显示，需要通过 Inspector 或 evidence bundle 查看。
