# S77 增量 · correctness-eval 命令（真代码正确性打分）

Slice 类型：Post-S77 审计重排下的第一批「真正确性 eval」增量（内部飞轮可信度）。不撞 DO_NOT_TOUCH、不撞冻结。

## 问题（审计验证）
run 的 `eval_report.overall.score` 是**状态分桶常量**（pass=0.9 / partial=0.6 / fail=0.2，见 `review_agent.py:_overall`）。真实退出码信号（`run_tests`/`run_command` 的 `ok`）虽已算进 `deterministic_checks.verification_pass_rate`，但**从不喂进 score**——一个测试只过 3/5、0 阻塞的 run 仍可得 0.9。对"内部 AI 编程发动机"而言,飞轮不可信先于一切,故第一步是**能按真实通过率打分**。

## 参考（reference-first，不重复造轮子）
SWE-bench / Aider 等的 correctness 度量本质是「跑测试→pass/fail」,不是结构或自评分。本增量采用同一思路的最小落地:**读已落盘的真实 tool-call 退出码,graded = 通过比**;不发明新评测框架、不改主 review。

## 做法（仅追加）
- 新文件 `src/asteria_runtime/commands/correctness_eval_command.py`:`CorrectnessEvalCommand(root, run_id)` 读 `tool_calls.jsonl` + `task_plan.json`,算 `command_verification_pass_rate`（run_tests/run_command 成功比）、`task_completion_rate`、`blocked_task_count`;**graded score = 真实通过率**（非分桶）。**无 executable 验证 → status=fail / score=0 / reason="correctness unproven"**（诚实:未证明 ≠ 通过,取代 0.9）。不重跑,只读证据。
- 输出 `run_dir/correctness_eval.json`,复用 `eval_report` schema（goal/artifact/trajectory/cost 段留空=诚实占位,非全量 review）。
- `cli.py` 挂 `correctness-eval` 子命令(`--root/--run-id/--json`),`help=SUPPRESS` 从默认帮助隐藏(maintainer/eval 层)。

## 验证（DoD）
- `tests/unit/test_correctness_eval_command.py`(5 例):graded 2/3≠0.9、全过=pass、无验证=fail-unproven、阻塞降 partial、无 run 空结果。
- 全量 `pytest tests/unit` **916 passed**;`mypy` 干净;CLI 端到端(dispatch/help/默认隐藏)通过。

## 边界 / 后续
- 本增量**只读已落盘证据**打分,不重跑、不改主 review score、不接受收门控。
- 后续可扩展:(a) `--command` 重跑真实验证做新鲜测量;(b) 把 graded 信号接入主 review 或 gate(须评估是否撞既有分桶测试/DO_NOT_TOUCH)。
- 姊妹增量(同批):`apply_patch` 支持标准 git `/dev/null` 建/删(`patch_tools.py`,+4 单测)。
