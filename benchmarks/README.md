# Agent Runtime Benchmarks

This directory contains stable MVP scenario definitions. They are intentionally
small and local-first so they can be used for regression checks without API keys
or network access.

Each benchmark includes:

- `benchmark.json`: machine-readable scenario metadata.
- Optional fixture files under `fixtures/`.
- Acceptance checks that can be turned into automated runners later.

Current deterministic benchmarks:

- `password_tool`: local-first goal expansion and final reporting.
- `failing_tests_project`: failed verification, repair, backup, and reporting.
- `compact_handoff`: context snapshot, handoff, sessions context, and verification summary recovery data.
- `file_renamer`: safe file-operation planning with a dry-run rename preview.
- `markdown_kb`: local markdown indexing, keyword search, verification, and reporting.
