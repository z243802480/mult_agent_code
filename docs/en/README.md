# Multi-Agent Autonomous Development System - English Documentation

This directory contains the English reference document set for the project.

The Chinese documents in `docs/zh/` are the source of truth for product direction, delivery planning, and current implementation status. English documents are secondary references and may lag behind the active Chinese roadmap.

Recommended order:

1. `PRODUCT_SPEC.md`
2. `ARCHITECTURE.md`
3. `DATA_MODEL.md`
4. `RUNTIME_COMMANDS.md`
5. `DELIVERY_PLAN.md`
6. `QUALITY_AND_EVALUATION.md`
7. `COST_SECURITY_RISK.md`
8. `REAL_MODEL_ACCEPTANCE.md`

Current phase:

```text
Orchestrated Agent Runtime OS stage
```

For the current status and near-term roadmap, read `docs/zh/当前状态与路线.md` first.

Verification:

- Local: `python -m pip install -e ".[dev]"`, then `bash scripts/verify.sh`.
- Docker: `docker build -t agent-runtime:verify .`, then `docker run --rm agent-runtime:verify`.
- Offline model smoke: set `AGENT_MODEL_PROVIDER=fake` before running CLI workflows.
- Local model smoke: set `AGENT_MODEL_PROVIDER=ollama` and `AGENT_MODEL_NAME=qwen2.5-coder:7b`.
- Tiered routing: set `AGENT_MODEL_STRONG_PROVIDER`, `AGENT_MODEL_MEDIUM_PROVIDER`, or
  `AGENT_MODEL_CHEAP_PROVIDER` to route strong, medium, and cheap model calls independently.
- Real model smoke: run `agent /model-check --root .`, then run a minimal `agent /run` in a temporary
  workspace. MiniMax `sk-cp-` keys are routed to the China endpoint automatically. Never commit real
  API keys; keep them in environment variables or secret storage only.
- Real model acceptance: run `python scripts/real_model_acceptance.py --suite core`, or
  `--suite nightly` when budget allows. Summaries include duration, model/tool calls, token estimates,
  repair attempts, task status counts, and review status.
