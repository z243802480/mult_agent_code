# Multi-Agent Autonomous Development System - English Documentation

This directory contains the English reference document set for the project.

The Chinese documents in `docs/zh/` are the source of truth for product direction, delivery
planning, and current implementation status. The English tree is a small, secondary set — kept
deliberately thin so it cannot drift. The standalone English mirrors of the architecture / product /
data-model / runtime-commands / delivery / quality / cost-security / acceptance docs were removed on
2026-07-03 because they had gone stale against the converged code (see
`docs/zh/已删除与已替代登记.md`); read the Chinese sources for those topics.

English docs kept here (independently useful, not mirrors):

- `MODEL_PROVIDER_SPEC.md` — the `ModelClient` interface / request-response contract.
- `DEVELOPMENT.md` — English developer quickstart (env, commands, verification).
- `examples/*.json` — control-surface contract fixtures (referenced by `docs/zh/运行命令.md` and the
  documentation-contract tests; NOT prose docs).

For everything else, start from the Chinese sources of truth:

1. `../zh/研发总计划.md` — the single execution plan.
2. `../zh/当前状态与路线.md` — the short current-status snapshot.
3. `../zh/架构设计.md`, `../zh/数据模型.md`, `../zh/产品规格.md`, `../zh/运行命令.md`,
   `../zh/质量与评估.md`, `../zh/成本安全与风险.md`, `../zh/真实模型验收.md` — architecture, data model,
   product spec, commands, quality, cost/security, acceptance.

Verification:

- Local: `python -m pip install -e ".[dev]"`, then `bash scripts/verify.sh`.
- Docker: `docker build -t asteria-runtime:verify .`, then `docker run --rm asteria-runtime:verify`.
- Offline model smoke: set `AGENT_MODEL_PROVIDER=fake` before running CLI workflows.
- Local model smoke: set `AGENT_MODEL_PROVIDER=ollama` and `AGENT_MODEL_NAME=qwen2.5-coder:7b`.
- Tiered routing: set `AGENT_MODEL_STRONG_PROVIDER`, `AGENT_MODEL_MEDIUM_PROVIDER`, or
  `AGENT_MODEL_CHEAP_PROVIDER` to route strong, medium, and cheap model calls independently.
- Real model smoke: run `asteria /model-check --root .`, then run a minimal `asteria /run` in a temporary
  workspace. MiniMax `sk-cp-` keys are routed to the China endpoint automatically. Never commit real
  API keys; keep them in environment variables or secret storage only.
- Real model acceptance: run `python scripts/real_model_acceptance.py --suite core`, or
  `--suite nightly` when budget allows. Summaries include duration, model/tool calls, token estimates,
  repair attempts, task status counts, and review status.
