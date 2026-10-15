# S97 完成回复的验证数量校准（2026-10-15）

## 真实复现

在 S94 的真实 Studio 会话 `run-20261015-0003` 中，浏览器主线程结尾称“pytest 运行结果显示全部 6 项检查通过”。同一 run 的 `validation_results.jsonl` 中 `run_tests` 原始 `pytest -v` 输出是 `collected 3 items` / `3 passed`。运行结果本身为完成并自动接受，问题是最后一句将混合汇总数误指为 pytest 用例数。

`RunCommand._validation_conclusion` 的 `6/6 checks` 来自 3 条验证记录加 3 次命令执行：包括 read_file 记录，且 `run_tests` 同时出现在记录和命令两边。`run_recap._build_context` 把 `6/6 checks` 提供给结尾模型；模型据此生成了错误归属的数量。原始临时会话只读对照，未读取 provider key，未更改运行账本。

## 修复与边界

- 结尾模型只收到验证状态，不再收到混合 `checks` 数量；提示明确说明没有测试用例计数。
- 模型若仍输出具体测试/检查数量，结尾回复回退到已有结构化状态句，不让无凭据数字进入新会话主线程。版本号 `0.1.0` 和无数量的验证结论保持可用。
- 运行时的原始验证账本、完成闸及旧会话文本保持原样。`validation_conclusion` 仍是其原有混合记录计数；本刀没有把它重新定义为 pytest 用例数。

## 验收

- Red→Green：S94 形状的 `6/6` 不再进入结尾提示，“pytest 6 项检查”被拒绝；英文数字、中文数字、比例数同样回退，正常无数量回复保留。
- `test_run_recap.py` 13/13；与用户工作流、validation-run、文档契约合跑 71/71；Studio hermetic smoke 41/41（需 provider key 的 4 项保持 SKIP）；所改 Python 文件 Ruff 检查与格式检查通过。远端 Verify 状态另行记录。
- 浏览器已只读回放原 S94 会话并与 `pytest -v` 账本逐项对照。旧会话中的历史错误句不会被改写；新行为由定向回归证明，本刀未重新调用真实 provider 生成新回复。
