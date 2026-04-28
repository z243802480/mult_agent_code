# Agent Runtime Benchmarks

This directory contains stable MVP scenario definitions. They are intentionally
small and local-first so they can be used for regression checks without API keys
or network access.

Each benchmark includes:

- `benchmark.json`: machine-readable scenario metadata.
- Optional fixture files under `fixtures/`.
- Acceptance checks that can be turned into automated runners later.

