# Slice B8 — 两份 schema 对齐 + 防漂闸(承 B7 backlog)

B7 顺手发现:`schemas/`(仓库根)与 `src/asteria_runtime/schemas/`(打包)两份 schema **已经漂了**。

## 为什么这是"只坑真用户"的一类 bug

`SchemaValidator` 优先用传入目录(开发/测试 = 仓库根 `schemas/`),**目录不存在才回落到包内副本**
(即**装成 wheel 之后**)。两份漂移 = **同一个运行时对象,在开发环境合法、装完 wheel 就被拒**。
**它只在真实用户那里炸。**

## 实测漂移(不是推测)

87 个同名 schema,**17 个字节不同**,而且**双向漂**——根多 15 个属性,包多 18 个,**谁都不是超集**,
所以"拷一份覆盖另一份"会**删掉活字段**。

**7 个 schema 的差异会真的改变校验结果**:

| schema | 差异 | 后果 |
| --- | --- | --- |
| `agent_run_graph` | **包内 required 多要** `worker_kind` / `parallel_safety` / `child_plan_refs` | 开发时写得下的记录,**装成 wheel 后被拒** |
| `validation_run` | **根 required 多要** `control_surface` | 反过来:wheel 接受、开发拒绝 |
| `model_call` / `model_route_check` | enum 只有根有 | 一边强制、一边不管 |
| `goal_spec` / `task` | enum 只有包有 | 同上 |
| `task` | 包有 `allowed_mcp`/`allowed_skills`/`mcp_servers`/`skill_catalog`(**MCP/Skills 是已生产接线的真功能**) | 根 schema 对真功能是瞎的 |

## 做法

1. **union 合并**(属性 / enum 值 / required 全部取并集)——因为双向漂,并集是唯一不丢东西的方向。
2. **证明零丢失**:断言合并结果是**两边旧版的严格超集**(逐属性/required/enum 比对,`lost = 0`)。
   *看 diff 行数是猜,这个断言才是证明。*
3. **union `required` 会让校验更严** → 必须真跑证明没拒掉合法记录:**全量 1279 passed**。
4. `scripts/sync_schemas.py`(+ `--check`):**红了怎么修**要有一条命令,否则下次还是手工拷。

## 防漂闸 —— 其实早就存在

`tests/unit/test_schema_packaging.py` **本来就有**一个棘轮:`KNOWN_SCHEMA_CONTENT_DRIFT` 白名单
(17 项)+ 一个 **"白名单不许过期"** 的守卫。我修完漂移,**那个守卫立刻红了**——它尽职地发现
"漂移没了,白名单该清了"。

漂移归零后,白名单和看管白名单的那个测试都成了**死机制** → 删掉,让内容一致性检查变成**无条件硬闸**;
另补一条反向断言(**只存在于包内、根里没有的 schema**同样非法——那种副本没人 review、只会继续漂)。

**守卫必须证明它真会咬**:注入一处假漂移 → 测试立刻红、`sync_schemas.py --check` 也报出来 → 恢复后转绿。
(不验这一下,防漂测试很可能又是个空过的断言 —— 见 B6 那次。)

## 教训(第二次踩同一个坑)
**改 JSON 不要用 `json.dumps` 往返** —— 第一版合并脚本重排了**全部 87×2 个文件**(174 文件 / 15038 行
假 diff),包括本就一致的 70 个。改成:**只重写真需要合并的 17 个,其余一律按字节对齐**(根文件一个字不动)。
B7 已经踩过一次(298 行假 diff),这次是同一个错的放大版。**JSON 文件的"最小改动"要靠文本插入或条件重写,
不能靠序列化器。**

## 后续
① 上下文预算快照(`context_budget_snapshots.jsonl` 的 `compact_boundary` / 重复内容浪费)
② 守门哑区(规划器给 prose 占位符而非路径时,续跑守门无从检查)
③ 专家进 `workers.jsonl` 成树节点(仅影响树形下钻,B7 已让**数字**正确)
