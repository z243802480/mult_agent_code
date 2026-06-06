# Slice S34 — Real Provider Dual-Worker + Production Gray Gate

## observed_pattern

- Phase 5 S31–S33 已闭合 maintainer 场景审计、gray DecisionPoint rollback、Beta friction。
- 下一出口：**真实 provider 双文件 disjoint harness case** + **生产 gray 就绪评估**（仍不默认 `parallel_writes`）。
- 对标 S23 maintainer probe：从 isolated probe → **scoped production gray**（须 S32 rollback 证据 + DecisionPoint）。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `phase5_dual_worker_case.json` | Phase 3 rolling 风格的 scoped real 编程 case 定义 |
| `swarm_production_gray.py` | 生产 gray 就绪：S32 drill + phase5d + flag rollout 前提 |
| `phase5f_production_gray_gate.json` | Phase 5 出口闸门（wave 6） |
| `swarm_holistic_check.py` | 脉搏扩展 phase5f contract tests |

## green_checks

```bash
pytest tests/unit/test_swarm_production_gray.py -q
pytest tests/integration/test_phase5f_production_gray_gate.py -q
python scripts/swarm_holistic_check.py --root . --skip-studio
```

## real_provider_signoff（optional · 签字前）

```bash
python scripts/real_model_smoke.py --matrix p1 --matrix-case dual_disjoint_files
```

记录于 `.asteria/validation_runs/`；**非 CI 阻塞**。

## discipline

- Beta 默认 **session_agent** 不变
- CLI `parallel_writes` 默认 **false**
- 不 refactor execute/run；不新增用户面 maintainer 命令
- 生产放量仅经 **DecisionPoint + rollback**（复用 S32 栈）
