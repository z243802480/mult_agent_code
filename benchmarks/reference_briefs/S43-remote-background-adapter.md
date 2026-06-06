# Slice S43 — Remote Background Run Adapter

## observed_pattern

- Claude Code Gateway / 云 agent：异步 durable run；MVP 先 **接口 + registry 意图**，真 VM defer。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `remote_background_adapter.py` | stub backend · `start --remote` |
| registry | `status: deferred` · `remote_adapter: stub` |
| projection | `remote_available: false` · `cloud_vm_deferred: true` |
| CLI | `asteria background start GOAL --remote` |

## do_not_copy

- 不引入第二 runtime
- 不默认 cloud 依赖

## green_checks

```bash
pytest tests/integration/test_phase8c_remote_background_adapter_gate.py -q
```
