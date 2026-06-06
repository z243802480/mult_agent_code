# Slice S9 — CapabilityManifest 注入与 catalog 审计

## observed_pattern（行业已验证）

- **Claude Code / Codex**：模型 loop 启动前装载 tool surface 与权限边界；调用 metadata 可追溯到 manifest hash。
- **OpenCode**：session 级 capability 与 task 选择 catalog 分离但可对账。

## asteria_mapping（我们怎么做）

- 文件：`agent_harness.py`、`prompt_envelope.py`、`capability_manifest_catalog.py`、`chat_command.py`
- 行为：`plan/execute/debug/review` 已有 PromptEnvelope；**chat/ask** 补齐 manifest + model_call metadata
- 审计：`capability_manifest_audit.catalog_aligned` 对照 `agent_loop_dispatch.task_dispatch[].capability_catalog` 与 manifest direct/model surface

## do_not_copy（禁止照搬）

- 把 maintainer gate 词汇暴露到 Ask 主线程
- 无 brief 扩 North Star / 蜂群

## green_checks

- `pytest tests/unit/test_capability_manifest_catalog.py -q`
- `pytest tests/integration/test_chat_capability_manifest.py -q`
- `pytest tests/unit/test_cli.py -q -k ask`
