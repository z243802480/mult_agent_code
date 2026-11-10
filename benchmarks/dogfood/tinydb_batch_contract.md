# S110 real-repository task: TinyDB batch consistency

Source: https://github.com/msiemens/tinydb at
`edff96aeb2616402e9489d46e90a592c05565621` (MIT, keep upstream license).
Archive SHA256: `99f6de856e39a5832a3e82fa75ec68150b4d20fb255dcffe82ede8597d725b6e`.
The executing Asteria package contains no implementation of this target behavior.

Improve `Table.update_multiple` only, plus necessary imports/docstring in `tinydb/table.py`.
Add meaningful regressions only in `tests/test_batch_consistency_s110.py`. Preserve all
original tests, other production methods/files, configuration and dependencies.

Public acceptance:

1. Accept any finite iterable of `(fields, condition)` pairs, including a single-pass
   generator. Every document must see the complete batch. Keep the existing document-major
   order (each document sees operations in supplied order); later conditions see earlier
   changes to that document. Preserve returned ID order and duplicates per matching pair.
2. If input iteration/unpacking, a condition or a field updater fails before commit,
   propagate the error and leave the database unchanged, including nested mutable values
   and other tables. Apply this to MemoryStorage (which returns shared objects) and
   JSONStorage. Existing cached queries remain valid and usable on failure; no storage
   write may have occurred. External side effects performed by user callbacks are outside
   this guarantee.
3. Successful non-empty updates perform one storage write and invalidate affected table
   query results. Persist values/IDs correctly on JSON close/reopen. An empty or unmatched
   batch returns `[]` without changing document contents; either zero or one storage write
   is acceptable for those no-ops. Preserve public document/ID behavior and other tables.
4. Preserve mapping and callable updater support. No general transaction framework,
   concurrency changes, cross-call transaction, atomic replacement of arbitrary failing
   storage implementations, or changes to other table operations are required.

Run the complete original `tests/` suite plus new regressions using the declared Python.
Confirm that `tinydb` is imported from this workspace. Do not change tests to weaken the
goal, install dependencies, use network/Git/subagents, or read credentials. Do not inspect
the executing Asteria package, installed TinyDB implementations, parent/sibling directories,
other experiments, reference solutions, controller scripts or hidden acceptance checks.
Normal interpreter/pytest invocation is allowed. Finish when verified; do not pad duration
or repeat unchanged verification to extend the run.

The independent oracle checks these public semantics, not helper names, code structure or
private metadata fields. Its source and results remain outside the target until execution
has ended. Baseline failures and all original input hashes are recorded before the goal.
