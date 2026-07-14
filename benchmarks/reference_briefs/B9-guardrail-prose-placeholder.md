# Slice B9 — 守门哑区:换个措辞就把干完的活判成失败

承 B7/B8 backlog 的"守门哑区"。**查下去发现:真 bug 不在守门,在完成闸。**

## 先证伪:哑区本身其实是被兜住的

`_methodology_stop_guardrail_decision`(pre_final 续跑守门)在 `expected_artifacts` 只剩 prose
占位符时 `expected` 为空 → `return None` → **这一层确实是哑的**(什么都不查)。

**但不该修一个已经被兜住的问题**:RA7b-4 的 `task_contract.check_completion_contract` 是下游的
确定性完成闸,`requires_changed_artifact` 会拦住"零产出宣告完成"。所以哑区**不是**产物层的正确性洞。

## 真 bug(实测,不是推测)

两处对"这是不是一个真文件路径"的判断**不一致**:

- **守门**用**结构判据** `_looks_like_path`(无空格 + 有分隔符或扩展名;`src/` 这种目录 scope 不算)。
- **完成闸** `_expected_changed_files` 用**一个写死的 4 项字符串黑名单**:
  `{"implementation artifact", "planning artifact", "src/", "tests/"}`。

于是只要规划器吐出黑名单**之外**的任何措辞,完成闸就把它当成"必须被修改的文件" → 永远匹配不上:

| `expected_changed_files` 的值 | 修前 |
| --- | --- |
| `implementation artifact`(黑名单原文) | ✅ 过 |
| `implementation artifacts`(**只是复数**) | ❌ **任务被判失败** |
| `the new notes module` | ❌ 被判失败 |
| `更新后的文档` | ❌ 被判失败 |

模型**真写了 `src/notes.py`、验证也通过了**,只因为规划器换了个措辞,任务就被判
"expected changed files were not modified"。

**这是把写死的字符串黑名单当类型判断用** —— 正是 ADR-0016 反对的"harness 假装懂认知"。
规划器是用自由文本写这些条目的,**没有任何固定词表能穷举它们**,判据必须是结构性的。

## 做法

- `looks_like_file_path()` 提到 `core/task_contract.py` 作**单一真源**(定义在真正执行它的那个契约旁边),
  守门改为 import 同一个判据 → **两处不可能再各自漂**。
- `_expected_changed_files` 改用结构判据,**删掉那个 4 项黑名单**(结构判据是它的严格超集:
  `implementation artifact` 有空格 → 不是路径;`src/` 结尾是斜杠 → 是目录 scope 不是交付物)。

## 不能减配 —— 三件事必须同时成立(已测)

1. **措辞不再影响判定**:上表四种写法现在全过。
2. **真文件路径依然被严格要求**:`expected_changed_files=["src/notes.py"]` 而模型写了别的文件 →
   仍判 `expected changed files were not modified`。**闸没被削弱。**
3. **零产出依然不许宣告完成**:prose 条目不再是"文件"了,但 `requires_changed_artifact` 仍然拦住
   "什么都没改就说做完了" —— **prose 不能变成绕过闸的后门**。

## Definition of Done
- 上述三条各有测试锁死 + `looks_like_file_path` 的结构性单测。
- 全量 **1283 passed** + mypy 棘轮零新增债。

## 后续
① 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary` / 重复内容浪费)
② 专家进 `workers.jsonl` 成树节点(仅影响树形下钻;**数字**在 B7 已经对了)
③ `path_in_write_scope` 里还有一个 `GENERIC_ARTIFACT_SCOPES` 常量,是**另一处**"prose 当 scope"的
   概念(写作用域语义,与"期望产出文件"不同,本刀不动)—— 若将来也出现措辞敏感的怪象,先看这里
