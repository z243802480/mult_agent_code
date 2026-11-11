# Public contract: validated cross-table batches

Add `TinyDB.apply_batch(operations, *, dry_run=False)` to the accepted readonly TinyDB
source artifact. A batch is a finite iterable consumed exactly once. Each operation is a
Mapping with exactly these keys:

- put: `{"op":"put", "table":<str>, "doc_id":<positive int, not bool>, "value":<Mapping>}`
- remove: `{"op":"remove", "table":<str>, "doc_id":<positive int, not bool>}`

All string table names, including empty and Unicode names, are allowed. Put replaces the
whole document at that explicit ID, creating a table/document if absent. Remove deletes
an existing document, leaves an existing empty table present, and does nothing for a
missing ID/table. Operations apply sequentially, including repeated targets.

Return exactly `{"inserted":int,"updated":int,"removed":int}` counting operations:
put absent increments inserted, put present increments updated even if equal, successful
remove increments removed; missing remove is zero. Reject unknown/extra/missing fields,
invalid operation/table/ID/value with ValueError. Non-iterable operations raises TypeError;
iterator exceptions propagate unchanged. dry_run must be an actual bool or raise TypeError.

Validation and detachment of ALL operations complete before any storage I/O; snapshot each
operation/value as it is consumed. Any invalid later operation or iterator/copy exception
causes zero reads and writes. Do not mutate caller input or storage-owned read objects.
Deeply detach put values and the staging storage state. For every valid batch (including
empty/no-op/dry-run), perform exactly one underlying storage.read. A normal batch with any
put or successful remove performs exactly one write after staging all operations; otherwise
zero writes. Storage read/write exceptions propagate unchanged. No rollback is promised
for a storage implementation that itself partially writes before failing.

dry_run computes the same sequential counts, but performs no writes, does not construct
Table handles and does not invalidate existing query or next-ID caches. It is allowed on
readonly handles. For dry_run=False, a readonly handle raises public ReadOnlyError BEFORE
consuming operations or any I/O, even for an empty batch. Validate dry_run's type first.

After a successful write, existing table handles must not return stale query results.
Subsequent insert on an affected existing handle must choose current maximum stored ID+1
without overwriting an explicit batch ID. Failed/no-write/dry-run batches must leave
cached queries and next-ID state unchanged. Implementations may use their own internals;
the external oracle judges public behavior plus evaluator-owned storage observations.

Preserve existing TinyDB APIs, readonly guarantees, custom storage factories, JSON storage
and original tests. Required deliverables: tinydb/database.py, docs/usage.rst, docs/api.rst,
NEW tests/test_apply_batch_s123.py. Both docs need semantics and examples. Allowed, not
required: tinydb/table.py and tinydb/__init__.py. Optional NEW tinydb/_batch.py only if the
chosen design needs it. These choices are not required deliverables. Do not change any
other source/config/LICENSE/old tests/AGENTS.md/TASK_CONTRACT.md or this contract. The old
task edit list is historical; this contract is current.

Use these commands, preverified in the actual guarded tool environment:

    /home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o pythonpath=. -o addopts= tests -q
    /home/administrator/.cache/asteria-s101/venv/bin/python -c "import sys,pathlib; sys.path.insert(0,'.'); import tinydb; print(tinydb.__file__); assert pathlib.Path(tinydb.__file__).resolve().is_relative_to(pathlib.Path.cwd()/'tinydb')"

No installs, network/Git/subagents/credentials, other experiments/reference answers,
outside-workspace scans, runtime or installed-package implementation introspection.
Sphinx/Ruff/mypy are unavailable and not required; do not install or claim them. Use ordinary
permitted navigation. No artificial pause/time padding; finish when verified.
