# Multi-Agent Autonomous Development System - English Documentation

This directory contains the maintainable English document set for the project.

The Chinese documents in `docs/zh/` are currently the source of truth for detailed planning. The English documents are concise mirrors intended for cross-language review.

Recommended order:

1. `PRODUCT_SPEC.md`
2. `ARCHITECTURE.md`
3. `DATA_MODEL.md`
4. `RUNTIME_COMMANDS.md`
5. `DELIVERY_PLAN.md`
6. `QUALITY_AND_EVALUATION.md`
7. `COST_SECURITY_RISK.md`

Current phase:

```text
Phase 1B: reproducible runtime environment and execution loop hardening
```

Verification:

- Local: `python -m pip install -e ".[dev]"`, then `bash scripts/verify.sh`.
- Docker: `docker build -t agent-runtime:verify .`, then `docker run --rm agent-runtime:verify`.
- Offline model smoke: set `AGENT_MODEL_PROVIDER=fake` before running CLI workflows.
- Local model smoke: set `AGENT_MODEL_PROVIDER=ollama` and `AGENT_MODEL_NAME=qwen2.5-coder:7b`.
